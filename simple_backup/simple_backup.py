#!/usr/bin/env python3

"""
A simple python script that calls rsync to perform a backup

Parameters can be specified on the command line or using a configuration file
Backup to a remote server is also supported (experimental)

Classes:
    MyFormatter
    Backup
"""
# Import libraries
import sys
import os
import warnings
from functools import wraps
from shutil import rmtree, which
import shlex
import argparse
import configparser
import logging
from logging import StreamHandler
from timeit import default_timer
from subprocess import Popen, PIPE, STDOUT
from datetime import datetime
from tempfile import mkstemp
from getpass import getpass

from dotenv import load_dotenv
import paramiko
from paramiko import RSAKey, Ed25519Key, ECDSAKey, DSSKey

warnings.filterwarnings('error')


try:
    from systemd import journal
except ImportError:
    journal = None

try:
    import dbus
except ImportError:
    pass


load_dotenv()
euid = os.geteuid()

if euid == 0:
    user = os.getenv('SUDO_USER')
    homedir = os.path.expanduser(f'~{user}')
else:
    homedir = os.getenv('HOME')

logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(os.path.basename(__file__))
c_handler = StreamHandler()

c_handler.setLevel(logging.INFO)
c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
logger.addHandler(c_handler)

if journal:
    j_handler = journal.JournalHandler()
    j_handler.setLevel(logging.INFO)
    j_format = logging.Formatter('%(levelname)s - %(message)s')
    j_handler.setFormatter(j_format)
    logger.addHandler(j_handler)


def timing(_logger):
    """Decorator to measure execution time of a function

        Parameters:
            _logger: Logger object
    """
    def decorator_timing(func):
        @wraps(func)
        def wrapper_timing(*args, **kwargs):
            start = default_timer()

            value = func(*args, **kwargs)

            end = default_timer()

            _logger.info(f'Elapsed time: {end - start:.3f} seconds')

            return value

        return wrapper_timing

    return decorator_timing


class MyFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    """Custom format for argparse help text"""


class Backup:
    """Main class defining parameters and functions for performing backup

    Attributes:
        inputs: list
            Files and folders that will be backup up
        output: str
            Path where the backup will be saved
        exclude: list
            List of files/folders/patterns to exclude from backup
        options: str
            String representing main backup options for rsync
        keep: int
            Number of old backup to preserve
        host: str
            Hostname of server (for remote backup)
        username: str
            Username for server login (for remote backup)
        ssh_keyfile: str
            Location of ssh key
        remove_before: bool
            Indicate if removing old backups will be performed before copying files

    Methods:
        check_params():
            Check if parameters for the backup are valid
        define_backup_dir():
            Define the actual backup dir
        remove_old_backups():
            Remove old backups if there are more than indicated by 'keep'
        find_last_backup():
            Get path of last backup (from last_backup symlink) for rsync --link-dest
        run():
            Perform the backup
    """

    def __init__(self, inputs, output, exclude, keep, options, host=None,
                 username=None, ssh_keyfile=None, remove_before=False):
        self.inputs = inputs
        self.output = output
        self.exclude = exclude
        self.options = options
        self.keep = keep
        self.host = host
        self.username = username
        self.ssh_keyfile = ssh_keyfile
        self.remove_before = remove_before
        self._last_backup = ''
        self._server = ''
        self._output_dir = ''
        self._inputs_path = ''
        self._exclude_path = ''
        self._remote = None
        self._err_flag = False
        self._ssh = None
        self._password_auth = False
        self._password = None

    def check_params(self):
        """Check if parameters for the backup are valid"""

        if self.inputs is None or len(self.inputs) == 0:
            logger.info('No files or directory specified for backup.')

            return False

        if self.output is None:
            logger.critical('No output path specified. Use -o argument or specify output path in configuration file')

            return False

        if self.host is not None and self.username is not None:
            self._remote = True

        if self._remote:
            self._ssh = self._ssh_connection()

            if self._ssh is None:
                sys.exit(1)

            _, stdout, _ = self._ssh.exec_command(f'if [ -d "{self.output}" ]; then echo "ok"; fi')

            output = stdout.read().decode('utf-8').strip()

            if output != 'ok':
                logger.critical('Output path for backup does not exist')

                return False
        else:
            if not os.path.isdir(self.output):
                logger.critical('Output path for backup does not exist')

                return False

        self.output = os.path.abspath(self.output)

        if self.keep is None:
            self.keep = -1

        return True

    # Function to create the actual backup directory
    def define_backup_dir(self):
        """Define the actual backup dir"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._output_dir = f'{self.output}/simple_backup/{now}'

        if self._remote:
            self._server = f'{self.username}@{self.host}:'

    def remove_old_backups(self):
        """Remove old backups if there are more than indicated by 'keep'"""

        if self._remote:
            _, stdout, _ = self._ssh.exec_command(f'ls {self.output}/simple_backup')

            dirs = stdout.read().decode('utf-8').strip().split('\n')

            if dirs.count('last_backup') > 0:
                dirs.remove('last_backup')

            n_backup = len(dirs) - 1
            count = 0

            if n_backup > self.keep:
                logger.info('Removing old backups...')
                dirs.sort()

                for i in range(n_backup - self.keep):
                    _, _, stderr = self._ssh.exec_command(f'rm -r "{self.output}/simple_backup/{dirs[i]}"')

                    err = stderr.read().decode('utf-8').strip().split('\n')[0]

                    if err != '':
                        logger.error('Error while removing backup %s.', {dirs[i]})
                        logger.error(err)
                    else:
                        count += 1
        else:
            try:
                dirs = os.listdir(f'{self.output}/simple_backup')
            except FileNotFoundError:
                return

            if dirs.count('last_backup') > 0:
                dirs.remove('last_backup')

            n_backup = len(dirs) - 1
            count = 0

            if n_backup > self.keep:
                logger.info('Removing old backups...')
                dirs.sort()

                for i in range(n_backup - self.keep):
                    try:
                        rmtree(f'{self.output}/simple_backup/{dirs[i]}')
                        count += 1
                    except FileNotFoundError:
                        logger.error('Error while removing backup %s. Directory not found', dirs[i])
                    except PermissionError:
                        logger.error('Error while removing backup %s. Permission denied', dirs[i])

        if count == 1:
            logger.info('Removed %d backup', count)
        elif count > 1:
            logger.info('Removed %d backups', count)

    def find_last_backup(self):
        """Get path of last backup (from last_backup symlink) for rsync --link-dest"""

        if self._remote:
            if self._ssh is None:
                logger.critical('SSH connection to server failed')
                sys.exit(1)

            _, stdout, _ = self._ssh.exec_command(f'readlink -v {self.output}/simple_backup/last_backup')
            last_backup = stdout.read().decode('utf-8').strip()

            if last_backup != '':
                _, stdout, _ = self._ssh.exec_command(f'if [ -d "{last_backup}" ]; then echo "ok"; fi')

                output = stdout.read().decode('utf-8').strip()

                if output == 'ok':
                    self._last_backup = last_backup
                else:
                    logger.info('No previous backups available')
            else:
                logger.info('No previous backups available')
        else:
            if os.path.islink(f'{self.output}/simple_backup/last_backup'):
                link = os.readlink(f'{self.output}/simple_backup/last_backup')

                if os.path.isdir(link):
                    self._last_backup = link
                else:
                    logger.info('No previous backups available')
            else:
                logger.info('No previous backups available')

    def _ssh_connection(self):
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())

        try:
            ssh.connect(self.host, username=self.username)

            return ssh
        except UserWarning:
            k = input(f'Unknown key for host {self.host}. Continue anyway? (Y/N) ')

            if k[0].upper() == 'Y':
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            else:
                return None
        except paramiko.SSHException:
            pass

        try:
            ssh.connect(self.host, username=self.username)

            return ssh
        except paramiko.SSHException:
            pass

        if self.ssh_keyfile is None:
            try:
                password = getpass(f'{self.username}@{self.host}\'s password: ')
                ssh.connect(self.host, username=self.username, password=password)

                self._password_auth = True
                os.environ['SSHPASS'] = password

                return ssh
            except paramiko.SSHException as e:
                logger.critical('Can\'t connect to the server.')
                logger.critical(e)

                return None

        pkey = None

        try:
            pkey = RSAKey.from_private_key_file(self.ssh_keyfile)
        except paramiko.PasswordRequiredException:
            password = getpass(f'Enter passwphrase for key \'{self.ssh_keyfile}\': ')

            try:
                pkey = RSAKey.from_private_key_file(self.ssh_keyfile, password)
            except paramiko.SSHException:
                pass

        if pkey is None:
            try:
                pkey = Ed25519Key.from_private_key_file(self.ssh_keyfile)
            except paramiko.PasswordRequiredException:
                try:
                    pkey = Ed25519Key.from_private_key_file(self.ssh_keyfile, password)
                except paramiko.SSHException:
                    pass

        if pkey is None:
            try:
                pkey = ECDSAKey.from_private_key_file(self.ssh_keyfile)
            except paramiko.PasswordRequiredException:
                try:
                    pkey = ECDSAKey.from_private_key_file(self.ssh_keyfile, password)
                except paramiko.SSHException:
                    pass

        if pkey is None:
            try:
                pkey = DSSKey.from_private_key_file(self.ssh_keyfile)
            except paramiko.PasswordRequiredException:
                try:
                    pkey = DSSKey.from_private_key_file(self.ssh_keyfile, password)
                except paramiko.SSHException:
                    pass

        try:
            ssh.connect(self.host, username=self.username, pkey=pkey)
        except paramiko.SSHException:
            logger.critical('SSH connection to server failed')

            return None

        return ssh

    # Function to read configuration file
    @timing(logger)
    def run(self):
        """Perform the backup"""

        logger.info('Starting backup...')

        try:
            _notify('Starting backup...')
        except NameError:
            pass

        self.define_backup_dir()
        self.find_last_backup()

        _, self._inputs_path = mkstemp(prefix='tmp_inputs', text=True)
        _, self._exclude_path = mkstemp(prefix='tmp_exclude', text=True)

        with open(self._inputs_path, 'w', encoding='utf-8') as fp:
            for i in self.inputs:
                if not os.path.exists(i):
                    logger.warning('Input %s not found. Skipping', i)
                else:
                    fp.write(i)
                    fp.write('\n')

        with open(self._exclude_path, 'w', encoding='utf-8') as fp:
            if self.exclude is not None:
                for e in self.exclude:
                    fp.write(e)
                    fp.write('\n')

        if self.keep != -1 and self.remove_before:
            self.remove_old_backups()

        logger.info('Copying files. This may take a long time...')

        if self._last_backup == '':
            rsync = f'/usr/bin/rsync {self.options} --exclude-from={self._exclude_path} ' +\
                    f'--files-from={self._inputs_path} / "{self._server}{self._output_dir}" ' +\
                    '--ignore-missing-args --mkpath --protect-args'
        else:
            rsync = f'/usr/bin/rsync {self.options} --link-dest="{self._last_backup}" --exclude-from=' +\
                    f'{self._exclude_path} --files-from={self._inputs_path} / "{self._server}{self._output_dir}" ' +\
                    '--ignore-missing-args --mkpath --protect-args'

        if euid == 0 and self.ssh_keyfile is not None:
            rsync = f'{rsync} -e \'ssh -i {self.ssh_keyfile}\''
        elif self._password_auth and which('sshpass'):
            rsync = f'{rsync} -e \'sshpass -e ssh -l {self.username}\''

        args = shlex.split(rsync)

        with Popen(args, stdin=PIPE, stdout=PIPE, stderr=STDOUT, shell=False) as p:
            output, _ = p.communicate()

            del os.environ['SSHPASS']

            if p.returncode != 0:
                self._err_flag = True

        output = output.decode("utf-8").split('\n')

        if self._err_flag:
            logger.error('rsync: %s', output)
        else:
            logger.info('rsync: %s', output[-3])
            logger.info('rsync: %s', output[-2])

        if self._remote and not self._err_flag:
            _, stdout, _ = \
                self._ssh.exec_command(f'if [ -L "{self.output}/simple_backup/last_backup" ]; then echo "ok"; fi')

            output = stdout.read().decode('utf-8').strip()

            if output == 'ok':
                _, _, stderr = self._ssh.exec_command(f'rm "{self.output}/simple_backup/last_backup"')

                err = stderr.read().decode('utf-8').strip()

                if err != '':
                    logger.error(err)
                    self._err_flag = True
        elif not self._err_flag:
            if os.path.islink(f'{self.output}/simple_backup/last_backup'):
                try:
                    os.remove(f'{self.output}/simple_backup/last_backup')
                except FileNotFoundError:
                    logger.error('Failed to remove last_backup link. File not found')
                    self._err_flag = True
                except PermissionError:
                    logger.error('Failed to remove last_backup link. Permission denied')
                    self._err_flag = True

        if self._remote and not self._err_flag:
            _, _, stderr =\
                self._ssh.exec_command(f'ln -s "{self._output_dir}" "{self.output}/simple_backup/last_backup"')

            err = stderr.read().decode('utf-8').strip()

            if err != '':
                logger.error(err)
                self._err_flag = True
        elif not self._err_flag:
            try:
                os.symlink(self._output_dir, f'{self.output}/simple_backup/last_backup', target_is_directory=True)
            except FileExistsError:
                logger.error('Failed to create last_backup link. Link already exists')
                self._err_flag = True
            except PermissionError:
                logger.error('Failed to create last_backup link. Permission denied')
                self._err_flag = True
            except FileNotFoundError:
                logger.critical('Failed to create backup')

                return 1

        if self.keep != -1 and not self.remove_before:
            self.remove_old_backups()

        os.remove(self._inputs_path)
        os.remove(self._exclude_path)

        logger.info('Backup completed')

        if self._err_flag:
            logger.warning('Some errors occurred')

            try:
                _notify('Backup finished with errors (check log for details)')
            except NameError:
                pass
        else:
            try:
                _notify('Backup finished')
            except NameError:
                pass


def _parse_arguments():
    parser = argparse.ArgumentParser(prog='simple_backup',
                                     description='Simple backup script written in Python that uses rsync to copy files',
                                     epilog='See simple_backup(1) manpage for full documentation',
                                     formatter_class=MyFormatter)

    parser.add_argument('-c', '--config', default=f'{homedir}/.config/simple_backup/simple_backup.conf',
                        help='Specify location of configuration file')
    parser.add_argument('-i', '--input', nargs='+', help='Paths/files to backup')
    parser.add_argument('-o', '--output', help='Output directory for the backup')
    parser.add_argument('-e', '--exclude', nargs='+', help='Files/directories/patterns to exclude from the backup')
    parser.add_argument('-k', '--keep', type=int, help='Number of old backups to keep')
    parser.add_argument('--host', help='Server hostname (for remote backup)')
    parser.add_argument('-u', '--username', help='Username to connect to server (for remote backup)')
    parser.add_argument('--keyfile', help='SSH key location')
    parser.add_argument('-s', '--checksum', action='store_true',
                        help='Use checksum rsync option to compare files')
    parser.add_argument('-z', '--compress', action='store_true', help='Compress data during the transfer')
    parser.add_argument('--remove-before-backup', action='store_true',
                        help='Remove old backups before executing the backup, instead of after')

    args = parser.parse_args()

    return args


def _read_config(config_file):
    if not os.path.isfile(config_file):
        logger.warning('Config file %s does not exist', config_file)

        return None, None, None, None, None, None, None

    config = configparser.ConfigParser()
    config.read(config_file)

    inputs = config.get('backup', 'inputs')
    inputs = inputs.split(',')
    output = config.get('backup', 'backup_dir')
    exclude = config.get('backup', 'exclude')
    exclude = exclude.split(',')
    keep = config.getint('backup', 'keep')

    try:
        host = config.get('server', 'host')
        username = config.get('server', 'username')
        ssh_keyfile = config.get('server', 'ssh_keyfile')
    except (configparser.NoSectionError, configparser.NoOptionError):
        host = None
        username = None
        ssh_keyfile = None

    return inputs, output, exclude, keep, host, username, ssh_keyfile


def _notify(text):
    _euid = os.geteuid()

    if _euid == 0:
        uid = os.getenv('SUDO_UID')
    else:
        uid = os.geteuid()

    os.seteuid(int(uid))
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'

    obj = dbus.SessionBus().get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
    obj = dbus.Interface(obj, 'org.freedesktop.Notifications')
    obj.Notify('', 0, '', 'simple_backup', text, [], {'urgency': 1}, 10000)

    os.seteuid(int(_euid))


def simple_backup():
    """Main"""

    args = _parse_arguments()
    inputs, output, exclude, keep, username, host, ssh_keyfile = _read_config(args.config)

    if args.input is not None:
        inputs = args.input

    if args.output is not None:
        output = args.output

    if args.exclude is not None:
        exclude = args.exclude

    if args.keep is not None:
        keep = args.keep

    if args.host is not None:
        host = args.host

    if args.username is not None:
        username = args.username

    if args.keyfile is not None:
        ssh_keyfile = args.keyfile

    backup_options = ['-a', '-r', '-v', '-h', '-H', '-X']

    if args.checksum:
        backup_options.append('-c')

    if args.compress:
        backup_options.append('-z')

    backup_options = ' '.join(backup_options)

    backup = Backup(inputs, output, exclude, keep, backup_options, host, username,
                    ssh_keyfile, remove_before=args.remove_before_backup)

    if backup.check_params():
        return backup.run()

    return 1


if __name__ == '__main__':
    simple_backup()
