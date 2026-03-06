#!/bin/bash
# GCP Free Tier e2-micro VM setup script for StockAlarm
# Run this ONCE from your local machine (with gcloud CLI installed)

set -e

PROJECT_ID=$(gcloud config get-value project)
ZONE="us-central1-a"
INSTANCE="stockalarm"

echo "=== Creating GCP e2-micro VM ==="
echo "Project: $PROJECT_ID"
echo "Zone: $ZONE"
echo "Instance: $INSTANCE"

# Create the VM (e2-micro is always-free in us-central1, us-east1, us-west1)
gcloud compute instances create $INSTANCE \
  --zone=$ZONE \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --tags=stockalarm

echo ""
echo "=== VM created. Next steps: ==="
echo "1. SSH into the VM:"
echo "   gcloud compute ssh $INSTANCE --zone=$ZONE"
echo ""
echo "2. On the VM, run:"
echo "   sudo apt update && sudo apt install -y python3-pip python3-venv git"
echo "   git clone <your-repo-url> StockAlarm"
echo "   cd StockAlarm"
echo "   python3 -m venv venv"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Create .env file:"
echo "   nano .env"
echo "   (paste TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)"
echo ""
echo "4. Set up systemd service:"
echo "   sudo cp stockalarm.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable stockalarm"
echo "   sudo systemctl start stockalarm"
echo ""
echo "5. Check logs:"
echo "   sudo journalctl -u stockalarm -f"
