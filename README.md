simple_backup
============
A simple backup script

## Description
simple_backup is a Python script that allows you to backup your files.
Parameters like input files/directories, output directory etc. can be specified in a configuration file, or on the command line.
Run:

```bash
simple_backup -h
```

to print all possible command line options.

## Dependencies
The script uses rsync to actually run the backup, so you will have to install it on your system. For example on Arch Linux:

```bash
sudo pacman -Syu rsync
```

It's also required to have python-dotenv

Optional dependencies are systemd-python to enable using systemd journal for logging, and dbus-python for desktop notifications.

## Install
To install the program, first clone the repository:

```bash
git clone https://github.com/Fuxino/simple_backup.git
```

Then install the tools required to build the package:

```bash
pip install --upgrade build wheel
```

Finally, run:

```bash
cd simple_backup
python -m build --wheel
python -m pip install dist/*.whl
```

For Arch Linux and Arch-based distros, two packages are available in the AUR (aur.archlinux.org):
- **simple_backup** for the release version
- **simple_backup-git** for the git version

