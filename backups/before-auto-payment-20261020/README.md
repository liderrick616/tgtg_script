# 🥡 TGTG Sniper Bot

Auto-reserve Too Good To Go surprise bags the instant they drop.

This bot monitors your target surprise bags, automatically reserves them when stock appears, and sends you an urgent push notification so you can complete payment in the official TGTG app within the ~5 minute hold window.

---

## ⚡ Quick Start

### 1. Install Python dependencies

```bash
cd "/Users/derrick/Desktop/tgtg script"
pip install -r requirements.txt
```

### 2. Configure your email

Edit `config.yaml` and set your Too Good To Go account email:

```yaml
tgtg:
  email: "your_real_email@example.com"
```

### 3. Authenticate

```bash
python main.py login
```

This sends a verification email from TGTG. Click the link in the email to complete login. Your credentials are saved (encrypted) locally so you don't need to re-authenticate.

### 4. Find your target item IDs

```bash
python main.py list-favorites
```

This shows all your favorited stores with their item IDs. Copy the IDs you want to snipe.

### 5. Configure targets

Edit `config.yaml` and add your target item IDs:

```yaml
targets:
  - item_id: "123456"
    name: "Amazing Bakery"
  - item_id: "789012"
    name: "Sushi Place"
```

Or monitor ALL your favorites:

```yaml
monitor_all_favorites: true
```

### 6. Run the bot

```bash
python main.py run
```

Press `Ctrl+C` to stop.

---

## 📱 Setting Up Notifications

### macOS Native Alerts (enabled by default)

No setup needed — the bot will display macOS notifications and play a sound when bags are detected.

### Telegram (recommended for phone alerts)

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
4. Start a chat with your new bot and send any message
5. Get your chat ID by visiting: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Update `config.yaml`:

```yaml
notifications:
  telegram:
    enabled: true
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "987654321"
```

### Discord Webhook

1. In your Discord server, go to Channel Settings → Integrations → Webhooks
2. Create a new webhook and copy the URL
3. Update `config.yaml`:

```yaml
notifications:
  discord:
    enabled: true
    webhook_url: "https://discord.com/api/webhooks/..."
```

### Test your notifications

```bash
python main.py test-notify
```

---

## ⚙️ Configuration Reference

### Polling Schedule

```yaml
polling:
  normal_interval: 90    # Seconds between polls (normal mode)
  burst_interval: 3      # Seconds between polls (burst mode)
  jitter_min: 0.5        # Min random delay added
  jitter_max: 1.8        # Max random delay added
  burst_windows:         # Times to poll aggressively
    - start: "08:00"
      end: "08:20"
  error_cooldown: 300    # Cooldown after a 403 block (seconds)
```

### Reservation

```yaml
reservation:
  auto_reserve: true     # Auto-reserve when stock detected?
  quantity: 1            # Number of bags to reserve
```

---

## 🛡️ Safety & Anti-Ban Tips

| Setting | Recommendation | Why |
|---------|---------------|-----|
| `normal_interval` | 60–120s | Avoids DataDome rate limits |
| `burst_interval` | 2–5s | Only during known drop windows |
| `jitter` | 0.5–1.8s | Randomizes timing to look human |
| Network | **Home WiFi** | Datacenter IPs are blocked on sight |
| Account | Test with throwaway first | Before using your main account |

---

## 🔧 CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py login` | Authenticate via email |
| `python main.py run` | Start the polling bot |
| `python main.py list-favorites` | Show all favorites with item IDs |
| `python main.py test-notify` | Send test notification |

---

## 📁 Project Structure

```
tgtg script/
├── config.yaml          # Your configuration
├── credentials.json     # Encrypted credentials (auto-generated)
├── main.py              # CLI entry point
├── auth.py              # Authentication & token management
├── poller.py            # Smart polling engine
├── reserver.py          # Order reservation logic
├── notifier.py          # Notification system
├── config_loader.py     # Config parser
├── logger_setup.py      # Logging setup
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

---

## ⚠️ Disclaimer

This bot uses an unofficial, reverse-engineered API. Too Good To Go does not provide a public API, and automated interaction may violate their Terms of Service. Use at your own risk. Always test with a throwaway account first.
