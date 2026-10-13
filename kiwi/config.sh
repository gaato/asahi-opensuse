#!/bin/bash

set -euxo pipefail
umask 022

test -f /.kconfig && . /.kconfig
test -f /.profile && . /.profile

echo "Configure image..."

#======================================
# Clear machine specific configuration
#--------------------------------------
## Clear machine-id on pre generated images
rm -f /etc/machine-id
touch /etc/machine-id
## remove random seed, the newly installed instance should make its own
rm -f /var/lib/systemd/random-seed

#======================================
# Delete & lock the root user password
#--------------------------------------
passwd -d root
passwd -l root

#======================================
# Setup default services
#--------------------------------------
systemctl enable NetworkManager.service
systemctl enable chronyd.service
# The openSUSE presets already claim this alias for display-manager-legacy.
# This image deliberately uses SDDM directly, including its Wayland greeter.
systemctl enable --force sddm.service
systemctl enable speakersafetyd.service

mkdir -p /var/log/journal

systemctl set-default graphical.target

# Use standard US Dvorak on the Apple JIS keyboard in all graphical sessions.
mkdir -p /etc/X11/xorg.conf.d /etc/skel/.config /var/lib/sddm/.config
cat > /etc/X11/xorg.conf.d/00-keyboard.conf <<EOF
Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "on"
    Option "XkbLayout" "us"
    Option "XkbVariant" "dvorak"
    Option "XkbModel" "apple"
EndSection
EOF
cat > /etc/skel/.config/kxkbrc <<EOF
[Layout]
Use=true
LayoutList=us
VariantList=dvorak
Model=apple
EOF
cp /etc/skel/.config/kxkbrc /var/lib/sddm/.config/kxkbrc
chown -R sddm:sddm /var/lib/sddm/.config
# KIWI may already have created the personalized user before config.sh runs.
for user_home in /home/*; do
    [ -d "$user_home" ] || continue
    mkdir -p "$user_home/.config"
    cp /etc/skel/.config/kxkbrc "$user_home/.config/kxkbrc"
    chown --reference="$user_home" "$user_home/.config" "$user_home/.config/kxkbrc"
done

#======================================
# Enable yast2-firstboot
#--------------------------------------
# touch /var/lib/YaST2/reconfig_system

#======================================
# Generate boot.bin
#--------------------------------------
mkdir -p /boot/efi/m1n1
update-m1n1 /boot/efi/m1n1/boot.bin
rm -rf /boot/.builder

# KIWI creates the final GRUB configuration after partitioning the image.

#======================================
# Default to Wayland
#--------------------------------------
mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/10-wayland-default.conf <<EOF
[General]
DisplayServer=wayland
EOF

exit 0
