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

## Install
To install the program, first clone the repository:

```bash
git clone https://github.com/Fuxino/simple_backup.git
```

Install tools required to build and install the package:

```bash
pip install --upgrade build installer wheel
```

Then run:

```bash
cd simple_backup
python -m build --wheel
python -m installer dist/*.whl
```

For Arch Linux and Arch-based distros, two packages are available in the AUR (aur.archlinux.org):
- **simple_backup** for the release version
- **simple_backup-git** for the git version

After installing, copy simple_backup.conf (if you used the PKGBUILD on Arch, it will be in /etc/simple_backup/) to $HOME/.config/simple_backup and edit is as needed.

