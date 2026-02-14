import asyncio
import json
import logging
import signal
import sys
import os

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.mqtt_client import MqttClient
from src.dtu.opendtu import OpenDTUAdapter
from src.meters.powermeter import PowerMeter
from src.controller import PIDController
from src.data_logger import DataLogger

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zero-export")


# Global toggle — controlled via MQTT
_enabled = asyncio.Event()
# Starts OFF — send 'on' to zeropower/set/enabled to activate


async def _handle_enable_cmd(topic: str, payload: str):
    val = payload.strip().lower()
    if val in ("1", "true", "on"):
        _enabled.set()
        logger.info("Zero-export ENABLED")
    elif val in ("0", "false", "off"):
        _enabled.clear()
        logger.info("Zero-export DISABLED (paused)")


async def _http_toggle(request):
    if _enabled.is_set():
        _enabled.clear()
        logger.info("Zero-export DISABLED via HTTP")
    else:
        _enabled.set()
        logger.info("Zero-export ENABLED via HTTP")
    redirect = request.query.get("redirect")
    if redirect:
        raise web.HTTPFound(location=redirect)
    state = "on" if _enabled.is_set() else "off"
    return web.json_response({"enabled": state})


async def _http_status(request):
    state = "on" if _enabled.is_set() else "off"
    return web.json_response({"enabled": state})


async def _start_http(host="0.0.0.0", port=8080):
    app = web.Application()
    app.router.add_get("/api/toggle", _http_toggle)
    app.router.add_get("/api/status", _http_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("HTTP control API on port %d", port)
    return runner


async def control_loop(
    cfg, mqtt: MqttClient, dtu: OpenDTUAdapter,
    meter: PowerMeter, pid: PIDController, telemetry: DataLogger,
):
    ctrl = cfg.control
    inverters = cfg.inverters
    poll_interval = cfg.powermeter.poll_interval_s
    loop_interval = ctrl.loop_interval_s
    limit_timeout = ctrl.set_limit_timeout_s

    await asyncio.sleep(3)
    logger.info("Control loop starting")

    await dtu.check_version_http()

    while True:
        try:
            active_inverters = []
            total_max_watt = 0
            total_min_watt = 0

            for inv in inverters:
                if not inv.enabled:
                    continue
                if not dtu.is_reachable(inv.serial):
                    logger.warning("Inverter %s not reachable", inv.serial)
                    continue
                active_inverters.append(inv)
                total_max_watt += inv.max_watt
                min_w = int(inv.inverter_watt * inv.min_watt_percent / 100)
                total_min_watt += min_w

            # Poll powermeter (full response)
            grid = await meter.read_full()
            grid_watts = grid.power
            logger.info("Grid power: %dW", int(grid_watts))

            # Record grid telemetry
            telemetry.record("grid", {
                "power": grid.power,
                "voltage": grid.voltage,
                "current": grid.current,
                "pf": grid.pf,
                "reactive": grid.reactive,
                "energy_imported": grid.total,
                "energy_exported": grid.total_returned,
            })

            # Record DTU status
            telemetry.record("dtu", {"online": 1.0 if dtu.is_dtu_online() else 0.0})

            # Record inverter telemetry
            for inv in active_inverters:
                inv_power = dtu.get_ac_power(inv.serial)
                inv_temp = dtu.get_temperature(inv.serial)
                limit_abs = dtu.get_limit_absolute(inv.serial)
                limit_rel = dtu.get_limit_relative(inv.serial)
                dc_power = dtu.get_dc_power(inv.serial)
                ac_voltage = dtu.get_ac_voltage(inv.serial)
                ac_current = dtu.get_ac_current(inv.serial)
                frequency = dtu.get_frequency(inv.serial)
                pf = dtu.get_power_factor(inv.serial)
                reactive = dtu.get_reactive_power(inv.serial)
                efficiency = dtu.get_efficiency(inv.serial)
                yield_day = dtu.get_yield_day(inv.serial)
                yield_total = dtu.get_yield_total(inv.serial)
                producing = dtu.is_producing(inv.serial)
                inv_tags = {"serial": inv.serial, "name": dtu.get_name(inv.serial)}

                telemetry.record(
                    "inverter",
                    {
                        "power": inv_power,
                        "dc_power": dc_power,
                        "temperature": inv_temp,
                        "limit": limit_abs,
                        "limit_relative": limit_rel,
                        "ac_voltage": ac_voltage,
                        "ac_current": ac_current,
                        "frequency": frequency,
                        "power_factor": pf,
                        "reactive_power": reactive,
                        "efficiency": efficiency,
                        "yield_day": yield_day,
                        "yield_total": yield_total,
                        "producing": 1.0 if producing else 0.0,
                    },
                    tags=inv_tags,
                )

                # Per-channel panel telemetry
                voltages = dtu.get_panel_voltages(inv.serial)
                currents = dtu.get_panel_currents(inv.serial)
                powers = dtu.get_panel_powers(inv.serial)
                ch_yield_day = dtu.get_panel_yield_day(inv.serial)
                ch_yield_total = dtu.get_panel_yield_total(inv.serial)
                ch_irradiation = dtu.get_panel_irradiation(inv.serial)
                for ch in range(len(voltages)):
                    telemetry.record(
                        "panel",
                        {
                            "voltage": voltages[ch],
                            "current": currents[ch] if ch < len(currents) else 0.0,
                            "power": powers[ch] if ch < len(powers) else 0.0,
                            "yield_day": ch_yield_day[ch] if ch < len(ch_yield_day) else 0.0,
                            "yield_total": ch_yield_total[ch] if ch < len(ch_yield_total) else 0.0,
                            "irradiation": ch_irradiation[ch] if ch < len(ch_irradiation) else 0.0,
                        },
                        tags={"serial": inv.serial, "channel": str(ch + 1)},
                    )

            # Control: only adjust limits when enabled
            if not _enabled.is_set():
                await mqtt.publish_state("enabled", "false")
                telemetry.record("control", {"enabled": 0.0, "setpoint": 0.0})
                logger.debug("Control paused, data still collected")
                await asyncio.sleep(loop_interval)
                continue

            await mqtt.publish_state("enabled", "true")
            telemetry.record("control", {"enabled": 1.0})

            if not active_inverters:
                logger.warning("No inverters reachable, waiting...")
                await asyncio.sleep(loop_interval)
                continue

            # Compute new setpoint
            new_limit = pid.compute(grid_watts, total_max_watt, total_min_watt)

            # Distribute limit across inverters proportionally
            remaining = new_limit
            for inv in active_inverters:
                share = int(new_limit * inv.max_watt / total_max_watt)
                min_w = int(inv.inverter_watt * inv.min_watt_percent / 100)
                share = max(min_w, min(inv.max_watt, share))

                factor = inv.get("compensate_factor", 1.0)
                if factor != 1.0:
                    share = int(share * factor)
                    share = max(min_w, min(inv.inverter_watt, share))

                await dtu.set_limit(inv.serial, share, mqtt)
                remaining -= share

                telemetry.record(
                    "control",
                    {"setpoint": float(share)},
                    tags={"serial": inv.serial},
                )

            # Publish state via MQTT
            await mqtt.publish_state("limit", new_limit)
            await mqtt.publish_state("grid_power", int(grid_watts))

            # Poll at higher frequency within the loop interval
            for _ in range(int(loop_interval / poll_interval) - 1):
                await asyncio.sleep(poll_interval)
                grid_watts = await meter.read_watts()

                if grid_watts > ctrl.max_point_w or (
                    grid_watts < ctrl.min_point_w and ctrl.fast_limit_decrease
                ):
                    new_limit = pid.compute(grid_watts, total_max_watt, total_min_watt)
                    for inv in active_inverters:
                        share = int(new_limit * inv.max_watt / total_max_watt)
                        min_w = int(inv.inverter_watt * inv.min_watt_percent / 100)
                        share = max(min_w, min(inv.max_watt, share))
                        await dtu.set_limit(inv.serial, share, mqtt)
                    break

        except Exception:
            logger.exception("Control loop error")
            await asyncio.sleep(loop_interval)


async def main():
    cfg = load_config(os.environ.get("CONFIG_PATH", "config.yaml"))

    mqtt = MqttClient(
        broker=cfg.mqtt.broker,
        port=int(cfg.mqtt.port),
        client_id=cfg.mqtt.client_id,
        topic_prefix=cfg.mqtt.topic_prefix,
    )

    dtu = OpenDTUAdapter(cfg, cfg.inverters)
    meter = PowerMeter(
        ip=cfg.powermeter.ip,
        user=cfg.powermeter.user,
        password=cfg.powermeter.password,
        emeter_index=cfg.powermeter.get("emeter_index", 0),
        meter_type=cfg.powermeter.type,
    )
    pid = PIDController(cfg)
    telemetry = DataLogger(cfg)

    # Register MQTT handlers
    opendtu_topic = cfg.mqtt.opendtu_topic
    mqtt.on_topic(f"{opendtu_topic}/#", dtu.handle_mqtt)

    # Enable/disable toggle via MQTT
    topic_prefix = cfg.mqtt.topic_prefix
    mqtt.on_topic(f"{topic_prefix}/set/enabled", _handle_enable_cmd)

    # Graceful shutdown
    stop = asyncio.Event()

    def _shutdown(sig):
        logger.info("Received %s, shutting down", sig.name)
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown, sig)

    logger.info("Zero Export Opt starting...")

    http_runner = await _start_http()

    tasks = [
        asyncio.create_task(mqtt.run()),
        asyncio.create_task(telemetry.run()),
        asyncio.create_task(control_loop(cfg, mqtt, dtu, meter, pid, telemetry)),
    ]

    await stop.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await telemetry.flush()
    await telemetry.close()
    await http_runner.cleanup()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
