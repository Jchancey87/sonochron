# Proxmox LXC — Fix CUDA for Container `sample-journal`

> The container can run `nvidia-smi` but `cuInit()` fails with error 999 (CUDA_ERROR_UNKNOWN).
> Root cause: cgroup v2 device allowlist is missing the nvidia-uvm devices.

---

## Step 1 — Get the UVM device major numbers (run on Proxmox HOST)

```bash
ls -la /dev/nvidia-uvm /dev/nvidia-uvm-tools /dev/nvidia0 /dev/nvidiactl
```

You'll see output like:
```
crw-rw-rw- 1 root root 195,   0 ...  /dev/nvidia0
crw-rw-rw- 1 root root 195, 255 ...  /dev/nvidiactl
crw-rw-rw- 1 root root 511,   0 ...  /dev/nvidia-uvm
crw-rw-rw- 1 root root 511,   1 ...  /dev/nvidia-uvm-tools
```

Note the major number for `nvidia-uvm` — it's typically **511** on modern kernels but varies.
The `195` for nvidia0/nvidiactl is always the same.

---

## Step 2 — Find your LXC VMID (run on Proxmox HOST)

```bash
grep -r "sample-journal\|192.168.0.204" /etc/pve/lxc/
# OR list all containers:
pct list
```

Your VMID will be something like `100`, `101`, etc.

---

## Step 3 — Edit the LXC config (run on Proxmox HOST)

```bash
nano /etc/pve/lxc/<VMID>.conf
```

Add these lines (substitute the real UVM major number from Step 1):

```
# NVIDIA GPU passthrough — cgroup2 device access
lxc.cgroup2.devices.allow: c 195:* rwm
lxc.cgroup2.devices.allow: c 511:* rwm
```

> **If nvidia-uvm major ≠ 511**, replace `511` with whatever `ls -la /dev/nvidia-uvm` showed.

Also make sure these mount entries are present (add if missing):
```
lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file
```

---

## Step 4 — Restart the container (run on Proxmox HOST)

```bash
pct stop <VMID> && pct start <VMID>
```

---

## Step 5 — Verify CUDA works (run inside container after restart)

```bash
cd /home/jackc/projects/sonochron/backend
.venv/bin/python -c "import torch; print('CUDA:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Expected output:
```
CUDA: True
NVIDIA GeForce GTX 1050 Ti
```

---

## Notes

- The `lxc.cgroup2.devices.allow` lines are **cgroup v2** syntax (Proxmox 7+)
- On Proxmox 6 (cgroup v1) you'd use `lxc.cgroup.devices.allow` instead
- The container is **unprivileged** — `lxc.mount.entry` bind-mounts are safe
- After CUDA is confirmed working, come back here and we'll install CLAP
