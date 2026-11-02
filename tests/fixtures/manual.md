---
title: Widget CLI Manual
---
# Installation

Install with pip:

```bash
pip install widget
```

# Configuration

Create `widget.toml`:

```toml
[server]
port = 8080
```

:::warning
Never commit secrets to `widget.toml`.
:::

# Usage

1. Start the server
2. Open the dashboard
   1. Log in
   2. Select a project

```bash
widget serve --port 8080
```

# Troubleshooting

If the port is in use, choose another with `--port`.
