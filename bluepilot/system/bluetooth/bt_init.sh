#!/bin/bash
# Bring up the comma 3X's WCN3990 Bluetooth on its se6 UART (/dev/ttyHS1 with the Citadel Bluetooth kernel).
# Adapted from comma's agnos-builder bluetooth branch (userspace/usr/comma/bt_init.sh, MIT). Run as root.
set -e

killall hciattach 2>/dev/null || true
sleep 1

# Power-cycle the chip through the btpower driver (MSM_BT_POWER): off, then on
python3 -c "import fcntl,os; fd=os.open('/dev/btpower',os.O_RDWR); fcntl.ioctl(fd,0xbfad,0); os.close(fd)" 2>/dev/null || true
sleep 2
python3 -c "import fcntl,os; fd=os.open('/dev/btpower',os.O_RDWR); fcntl.ioctl(fd,0xbfad,1); os.close(fd)"
sleep 3

rfkill unblock bluetooth
sleep 1

# hciattach forks a daemon that keeps hci0 attached
hciattach -s 115200 /dev/ttyHS1 qualcomm 115200 flow

for _ in $(seq 1 10); do
  hciconfig hci0 up 2>/dev/null && exit 0
  sleep 1
done
echo "hci0 did not come up" >&2
exit 1
