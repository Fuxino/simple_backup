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

## Remote backup
> **Warning**
> This feature is experimental

It's possible to use a remote server as destination for the backup. Just use the --username (or -u) and --host arguments (or set them in the configuration file).
For this to work, rsync must be installed on the server too.

### Server authentication
The best way to handle the authentication is to have an ssh agent running on your system, otherwise if a passphrase is necessary to unlock the ssh key, it will be necessary to enter it more than once.
If needed, it's possible to specify the ssh key location with the --keyfile argument or in the configuration file.

To be able to connect to the user's ssh agent when running simple_backup with sudo, make sure to preserve the SSH_AUTH_SOCK environment variable. For example:

```bash
sudo --preserve-env=SSH_AUTH_SOCK -s simple_backup [options]
```

or by editing the sudoers file.
If SSH key authentication is not available, password authentication will be used instead.
Check the man page for more details.
