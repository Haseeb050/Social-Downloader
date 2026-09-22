# Social Downloader - AWS EC2 Deployment Details & Cheatsheet

Ye file aapke AWS EC2 deployment ki saari details aur commands ko save rakhne ke liye banayi gayi hai.

---

## 🌐 Server Details
- **Cloud Provider**: AWS EC2 (Free Tier Eligible)
- **Instance Type**: `t3.micro` / `t2.micro` (Ubuntu 24.04 LTS)
- **Public IP**: `51.21.251.244`
- **Application URL**: `http://51.21.251.244:8000` ya `http://51.21.251.244`

---

## 🍪 YouTube Cookies & Bot Detection Fix
YouTube AWS / Cloud IPs ko block karta hai. Iska hal:

1. **Node.js aur FFmpeg Install karein** (JS Challenge Solve karne ke liye):
   ```bash
   sudo apt update && sudo apt install -y nodejs ffmpeg
   ```
2. **Project dependencies update karein**:
   ```bash
   cd /home/ubuntu/Social-Downloader
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Cookies file ensure karein**:
   `www.youtube.com_cookies.txt` ya `cookies.txt` project folder mein honi chahiye.

---

## ⚙️ Service & Background Management
Aapki app **systemd** service ke zariye 24/7 background mein run hoti hai:

- **Service Name**: `social-downloader.service`
- **Status check karne ke liye**:
  ```bash
  sudo systemctl status social-downloader
  ```
- **Service Restart karne ke liye**:
  ```bash
  sudo systemctl restart social-downloader
  ```
- **Service Stop karne ke liye**:
  ```bash
  sudo systemctl stop social-downloader
  ```
- **Logs / Errors dekhne ke liye**:
  ```bash
  sudo journalctl -u social-downloader -f
  ```

---

## 🔄 Future mein Code Update / Redeploy Karne Ka Tareeqa
Jab bhi aap local code GitHub par push karein, EC2 terminal par bas ye commands chalayein:

```bash
cd /home/ubuntu/Social-Downloader
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart social-downloader
```

---

## 🛡️ Firewall & Ports
- **SSH (22)**: Server terminal connection ke liye
- **HTTP (80)**: Web traffic ke liye
- **Custom TCP (8000)**: FastAPI direct port ke liye
- **Port 80 to 8000 redirection rule**:
  ```bash
  sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000
  ```
