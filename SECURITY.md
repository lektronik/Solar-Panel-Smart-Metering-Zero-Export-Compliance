# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Reporting a Vulnerability

Use this project at your own risk.

If you discover a security vulnerability within this project, please **DO NOT** open a public issue.

Instead, please report it by contacting the repository owner directly or using GitHub's "Report a vulnerability" feature if enabled.

## Best Practices for IoT & Solar

This project involves controlling hardware (Inverters) and managing network credentials.

1.  **Network Isolation**: We strongly recommend running this stack on a **trusted local network** or a dedicated VLAN. Do **NOT** expose the MQTT broker (port 1883) or the web interface to the public internet without proper authentication (TLS/SSL) and firewall rules.
2.  **Credentials**: Never commit your `.env` file or `config.yaml` containing real passwords to GitHub. Use the provided `.env.example`.
3.  **Hardware Limits**: Always configure reasonable `max_watt` limits in `config.yaml` to prevent accidental hardware stress.
4.  **Updates**: Keep your Docker images (Mosquitto, InfluxDB, Grafana) up to date.
