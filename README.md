# asahi-opensuse

This repository contains kiwi configs and rpmbuild spec files in order to install openSUSE Tumbleweed to an Apple Silicon machine. I don't plan on releasing images for installation of others as these require commitment and dedication. This repository **primarily serves as backup for me** but hopefully it will be useful for others.

If you intend to use these to install a daily driver system, I **HIGHLY RECOMMEND** to just use the official Fedora Asahi Remix flagship distribution or any endorsed distros found here: [Distro Guidelines](https://asahilinux.org/docs/alt/policy/). It will save yourself from issues and headaches as the files here need more polishing and rigourous testing.

_**Please use at your own risk**_.


## Current State

I am currently running openSUSE Tumbleweed on an Apple Macbook Air M1 (2020) as of May 2026.

![openSUSE Tumbleweed on MBA M1](./images/asahi-tumbleweed-mba-m1.png)


## HOWTO

The initial creation of the packages and installation image was done in openSUSE Tumbleweed running in macOS via UTM. All updates to the packages were performed in the actual openSUSE Tumbleweed installation via local OBS.

In a nutshell, the flow of the building process is:
- Generate packages using the provided spec files (refer to [OBS project](https://build.opensuse.org/project/show/home:mrkcee)) or use built packages from OBS (USE AT YOUR OWN RISK)
- Create local repository (createrepo)
- Configure installation image by editing kiwi config files
- Generate raw image using kiwi-ng script
- Generate the installer images using the make-installer script
- Host the generated tar archive using a local http server
- Create installer using asahi-installer (or just use/patch the official one)
- Run the installer

Good luck :D

## This fork: M1 MacBook Air build

This fork uses [home:gaato:asahi](https://build.opensuse.org/project/show/home:gaato:asahi)
for Asahi packages and keeps `/boot` inside the Btrfs root filesystem so kernel,
initrd, and modules stay together during Snapper rollback. The image uses standard
US Dvorak on an Apple JIS keyboard, the Asia/Tokyo time zone, and an English UI.

Build in an **aarch64 openSUSE Tumbleweed VM**. Python 3.11 or newer is required.
The personalized image contains a login password hash; do not publish it or its logs.

1. Clone this fork and create `kiwi/users.local.xml` with
   `python3 scripts/configure-user.py YOUR_USER`. The helper prompts locally and
   stores only a hash in a file with mode 0600; Git ignores it. Alternatively, with
   the owner's consent, root can reuse an existing local account's hash with
   `python3 scripts/configure-user.py gaato --from-local-user`.
2. In the dedicated build VM, run `sudo bash scripts/prepare-vm.sh`. This installs
   the build tools and fetches the OBS signing key. The private user include must
   already exist; this step never copies a password hash automatically.
3. Wait until the required packages in `home:gaato:asahi/openSUSE_Factory_ARM`
   are built and published, including `kernel-asahi`, `dtb-apple`, `m1n1`, and
   `u-boot-asahi`. Do not mix a partial publication with a different kernel/DTB repo.
4. Run `sh kiwi/kiwi-tumbleweed-kde.sh`. Each build uses a fresh output directory
   inside the private `builds/` directory; an existing target is never erased. An
   explicit target and signing-key file can be supplied as its first and second
   arguments. An explicit target's parent must already have mode 0700. The image
   itself is built with umask 022 so its system files get normal permissions.
5. Package the resulting raw image with
   `sh kiwi/make-installer.sh PATH_TO_RAW PRIVATE_OUTPUT_DIRECTORY`.
   The packager checks the sector size, two-partition layout, filesystem types,
   boot artifacts, and ZIP integrity. It also writes a SHA-256 checksum.

For a complete build-and-package run in the dedicated prepared VM, root can run
`bash scripts/run-build.sh`. It prints a private run directory under `builds/`
and writes separate build and packaging logs there. The default artifact owner
is `gaato` (or `SUDO_USER` when launched through sudo). Read progress with
`python3 scripts/build-status.py RUN_DIRECTORY`; this suppresses credential-related
log details. A `status` file records completion or failure.

The output layout is:

```text
PRIVATE_OUTPUT_DIRECTORY/
  installer_data.json
  SHA256SUMS
  os/Tumbleweed-KDE.zip
```

Use the current official Asahi installer release. In its extracted working
directory, use the generated `installer_data.json` and set `REPO_BASE` to the
absolute private output directory before starting `install.sh`. The manifest's
relative package name makes the installer read the ZIP locally, without a web
server. Preserve the installer's boot files and support code. Current installer
releases also set the APFS bootability flag required by macOS 27.

Packaging validation can be run with `python3 tests/test_packaging.py -v` on Linux.
The integration test uses temporary regular files containing FAT and Btrfs
filesystems, not block devices; its dummy EFI binaries test packaging, not booting.
Actual Apple Silicon boot, graphics, audio, firmware extraction, and keyboard
behavior still require verification on the target Mac.

The optional Kamoso camera application is not preinstalled: its current package
requires `gstreamer-plugins-good-qtqml6`, which openSUSE disables on aarch64 because
of its GLES configuration. This does not remove Plasma or the camera kernel
driver. OpenH264 uses `libopenh264-8` and the plugin now shipped in
`gstreamer-plugins-bad`, not the obsolete standalone plugin package.

## Big thanks to the following:
- ivabus - for the initial configs
- Fedora Asahi SIG Team - basis of some specs
- tpwrules / NixOS on Apple Silicon - basis of some specs
- openSUSE maintainers - basis of some specs
- openSUSE project - for openSUSE Tumblweed, KIWI, Snapper, and Open Build Service
- SUSE and others - for sponsoring openSUSE
- Asahi Linux team and contributors - for creating Asahi Linux and other modules
- Folks who have provided their feedback and constructive comments

