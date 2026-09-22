# Social Downloader - AWS EC2 Deployment Details & Cheatsheet

Ye file aapke AWS EC2 deployment ki saari details aur commands ko save rakhne ke liye banayi gayi hai.

---

## 🌐 Server Details
- **Cloud Provider**: AWS EC2 (Free Tier Eligible)
- **Instance Type**: `t3.micro` / `t2.micro` (Ubuntu 24.04 LTS)
- **Public IP**: `51.21.251.244`
- **Application URL**: `http://51.21.251.244:8000` ya `http://51.21.251.244`

---

## ⚡ Dual-Engine YouTube & Bot Bypass Architecture
Backend ab **Dual-Engine Pipeline (`yt-dlp` + `pytubefix`)** use karta hai:
- **Engine 1 (`yt-dlp`)**: Multi-client fallback (`ios`, `mweb`, `web`).
- **Engine 2 (`pytubefix`)**: Agar YouTube bot challenge / 429 throw kare, system automatically background mein InnerTube engine se video download kar leta hai.
- **Proxy Ready**: Future high-traffic ke liye `.env` mein `PROXY_URL=http://...` add kar sakte hain.

---

## 🚀 Server Par Update Apply Karne Ka Tareeqa (3 Steps)
EC2 terminal par bas ye commands run karein:

```bash
cd /home/ubuntu/Social-Downloader
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart social-downloader
```

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
