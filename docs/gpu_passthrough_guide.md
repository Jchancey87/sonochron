# Proxmox LXC GPU Passthrough Guide (NVIDIA GTX 1050 Ti Setup)

This document details how we configured NVIDIA GPU passthrough from our Proxmox VE host to the unprivileged LXC container (`sample-journal`) for the Sonochron project. Use this guide to set up similar passthroughs on other containers.

---

## 1. Environment Reference
* **Proxmox Host IP:** `192.168.0.204` (approx)
* **LXC Container Name:** `sample-journal`
* **GPU:** NVIDIA GeForce GTX 1050 Ti with Max-Q Design (4 GB VRAM)
* **Host Driver Version:** `580.159.04`
* **Host CUDA Version:** `13.0`
* **Container Python Environment:** PyTorch running on CUDA 11.8 (via `cu118` build for compatibility with the GTX 1050 Ti `sm_61` compute capability).

---

## 2. Architecture Overview
In an LXC container, the container shares the host kernel. This means:
1. The physical GPU driver runs **only** on the Proxmox Host.
2. The LXC container requires the **exact same version** of the user-space NVIDIA driver libraries installed inside it, but **without** compilation of the kernel module (using the `--no-kernel-module` flag).
3. The host's GPU device nodes (like `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`) must be mapped directly into the container.
4. The container's access to these device files must be permitted via Proxmox's `cgroup v2` device access rules.

---

## 3. Step-by-Step Configuration

### Step A: Install Drivers on the Proxmox Host
1. Disable the open-source Nouveau driver on the host if it's active:
   ```bash
   echo "blacklist nouveau" >> /etc/modprobe.d/blacklist-nouveau.conf
   echo "options nouveau modeset=0" >> /etc/modprobe.d/blacklist-nouveau.conf
   update-initramfs -u
   reboot
   ```
2. Download and install the host NVIDIA driver (e.g., version `580.159.04`):
   ```bash
   chmod +x NVIDIA-Linux-x86_64-580.159.04.run
   ./NVIDIA-Linux-x86_64-580.159.04.run --no-questions --ui=none
   ```
3. Verify the installation on the host:
   ```bash
   nvidia-smi
   ```

### Step B: Identify Host Device Major Numbers
NVIDIA uses unified memory (`nvidia-uvm`) for CUDA workloads. Device node major numbers are dynamically assigned by the kernel for UVM.
1. Run this on the Proxmox host:
   ```bash
   ls -la /dev/nvidia*
   ```
2. Identify the major numbers in the output. For example:
   ```text
   crw-rw-rw- 1 root root 195,   0 Jun  7 12:00 /dev/nvidia0
   crw-rw-rw- 1 root root 195, 255 Jun  7 12:00 /dev/nvidiactl
   crw-rw-rw- 1 root root 511,   0 Jun  7 12:05 /dev/nvidia-uvm
   crw-rw-rw- 1 root root 511,   1 Jun  7 12:05 /dev/nvidia-uvm-tools
   ```
   *Note: `195` is standard for nvidia/nvidiactl, but the UVM major number (here `511`) can vary on host reboot.*

### Step C: Configure the LXC Container on the Host
1. Find the VMID of your target LXC container (e.g., `100`):
   ```bash
   pct list
   ```
2. Open the container configuration file on the host (e.g., `/etc/pve/lxc/100.conf`):
   ```bash
   nano /etc/pve/lxc/100.conf
   ```
3. Add the following cgroup permissions and device bind-mounts. **Make sure the UVM major number (e.g., `511`) matches what you found in Step B:**
   ```ini
   # NVIDIA GPU passthrough — cgroup2 device access
   lxc.cgroup2.devices.allow: c 195:* rwm
   lxc.cgroup2.devices.allow: c 511:* rwm

   # Bind-mounts for GPU device nodes
   lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
   lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
   lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
   lxc.mount.entry: /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file
   ```
4. Restart the container from the host to apply:
   ```bash
   pct stop <VMID> && pct start <VMID>
   ```

### Step D: Install NVIDIA Libraries in the Container
1. Enter the LXC container (or SSH into it).
2. Download the **exact same** version of the NVIDIA driver installer (`580.159.04`):
   ```bash
   wget https://us.download.nvidia.com/XFree86/Linux-x86_64/580.159.04/NVIDIA-Linux-x86_64-580.159.04.run
   ```
3. Run the installer inside the container **without compiling kernel modules**:
   ```bash
   chmod +x NVIDIA-Linux-x86_64-580.159.04.run
   ./NVIDIA-Linux-x86_64-580.159.04.run --no-kernel-module --no-questions --ui=none
   ```

---

## 4. Verification

### Step A: Verify `nvidia-smi`
Inside the container, run:
```bash
nvidia-smi
```
It should print the GPU details and confirm that user-space libraries are speaking to the kernel module.

### Step B: Verify PyTorch/CUDA
Inside the Python virtual environment of the container, run:
```bash
python3 -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
```
Expected output:
```text
CUDA available: True
Device Name: NVIDIA GeForce GTX 1050 Ti
```

---

## 5. Key Troubleshooting & Gotchas

### ⚠️ Issue 1: `nvidia-smi` works, but CUDA fails (`CUDA_ERROR_UNKNOWN` or error code 999)
* **Symptom:** Running `nvidia-smi` inside the container works perfectly, but running PyTorch/CUDA code returns `False` or raises `cuInit` initialization errors.
* **Root Cause:** The `nvidia-uvm` (Unified Memory) device node was not mounted, or the container was not granted cgroups permission for it.
* **Fix:** Check `ls -la /dev/nvidia-uvm` on the host. Ensure its major number (usually `511`) matches the configuration rule `lxc.cgroup2.devices.allow: c <MAJOR>:* rwm` in the container `.conf` file.

### ⚠️ Issue 2: Dynamically Changing UVM Major Number on Host Reboot
* **Symptom:** CUDA worked before, but stopped working after a host reboot.
* **Root Cause:** The major device number for `nvidia-uvm` is allocated dynamically by the host kernel when the module loads. If it shifts (e.g. from `511` to `509`), the container will be blocked from accessing it.
* **Workarounds:**
  1. Manually update `/etc/pve/lxc/<VMID>.conf` with the new major number and restart the container.
  2. Or, pin the UVM major number on the Proxmox host using a modprobe config file (e.g., `/etc/modprobe.d/nvidia.conf`):
     ```bash
     options nvidia-uvm uvm_major=511
     ```
     *(Make sure to update initramfs and reboot host if changing this option.)*

### ⚠️ Issue 3: Container/Host Driver Mismatch
* **Symptom:** Driver version mismatch errors in `dmesg` or when calling CUDA.
* **Root Cause:** Container driver version does not match host driver version.
* **Fix:** Re-run the installer inside the container using the exact version currently active on the host.
