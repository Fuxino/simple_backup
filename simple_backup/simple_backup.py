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
from glob import glob

from dotenv import load_dotenv

warnings.filterwarnings('error')

try:
    import paramiko
    from paramiko import RSAKey, Ed25519Key, ECDSAKey, DSSKey
except ImportError:
    pass

try:
    from systemd import journal
except ImportError:
    journal = None

try:
    import dbus
except ImportError:
    pass


load_dotenv()
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
        ssh_host: str
            Hostname of server (for remote backup)
        ssh_user: str
            Username for server login (for remote backup)
        ssh_keyfile: str
            Location of ssh key
        remote_sudo: bool
            Run remote rsync with sudo
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

    def __init__(self, inputs, output, exclude, keep, options, ssh_host=None, ssh_user=None,
                 ssh_keyfile=None, remote_sudo=False, remove_before=False, verbose=False):
        self.inputs = inputs
        self.output = output
        self.exclude = exclude
        self.options = options
        self.keep = keep
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_keyfile = ssh_keyfile
        self.remote_sudo = remote_sudo
        self._remove_before = remove_before
        self._verbose = verbose
        self._last_backup = ''
        self._server = ''
        self._output_dir = ''
        self._inputs_path = ''
        self._exclude_path = ''
        self._remote = None
        self._ssh = None
        self._password_auth = False
        self._password = None

    def check_params(self, homedir=''):
        """Check if parameters for the backup are valid"""

        if self.inputs is None or len(self.inputs) == 0:
            logger.info('No existing files or directories specified for backup. Nothing to do')

            return 1

        if self.output is None:
            logger.critical('No output path specified. Use -o argument or specify output path in configuration file')

            return 2

        if self.ssh_host is not None and self.ssh_user is not None:
            self._remote = True

        if self._remote:
            self._ssh = self._ssh_connect(homedir)

            if self._ssh is None:
                return 5

            _, stdout, _ = self._ssh.exec_command(f'if [ -d "{self.output}" ]; then echo "ok"; fi')

            output = stdout.read().decode('utf-8').strip()

            if output != 'ok':
                logger.critical('Output path for backup does not exist')

                return 2
        else:
            if not os.path.isdir(self.output):
                logger.critical('Output path for backup does not exist')

                return 2

        self.output = os.path.abspath(self.output)

        if self.keep is None:
            self.keep = -1

        return 0

    # Function to create the actual backup directory
    def define_backup_dir(self):
        """Define the actual backup dir"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._output_dir = f'{self.output}/simple_backup/{now}'

        if self._remote:
            self._server = f'{self.ssh_user}@{self.ssh_host}:'

    def remove_old_backups(self):
        """Remove old backups if there are more than indicated by 'keep'"""

        if self._remote:
            _, stdout, _ = self._ssh.exec_command(f'ls {self.output}/simple_backup')

            dirs = stdout.read().decode('utf-8').strip().split('\n')

            n_backup = len(dirs)

            if not self._remove_before:
                n_backup -= 1

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

            n_backup = len(dirs)

            if not self._remove_before:
                n_backup -= 1

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
                sys.exit(5)

            _, stdout, _ = self._ssh.exec_command(f'find {self.output}/simple_backup/ -mindepth 1 -maxdepth 1 -type d | sort')
            output = stdout.read().decode('utf-8').strip().split('\n')

            if output[-1] != '':
                self._last_backup = output[-1]
            else:
                logger.info('No previous backups available')
        else:
            try:
                dirs = sorted([f.path for f in os.scandir(f'{self.output}/simple_backup') if f.is_dir(follow_symlinks=False)])
            except FileNotFoundError:
                logger.info('No previous backups available')

                return
            except PermissionError:
                logger.critical('Cannot access the backup directory. Permission denied')

                try:
                    notify('Backup failed (check log for details)')
                except NameError:
                    pass

                sys.exit(3)

            try:
                self._last_backup = dirs[-1]
            except IndexError:
                logger.info('No previous backups available')

    def _ssh_connect(self, homedir=''):
        try:
            ssh = paramiko.SSHClient()
        except NameError:
            logger.error('Install paramiko for ssh support')
            return None

        try:
            ssh.load_host_keys(filename=f'{homedir}/.ssh/known_hosts')
        except FileNotFoundError:
            logger.warning(f'Cannot find file {homedir}/.ssh/known_hosts')

        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())

        try:
            ssh.connect(self.ssh_host, username=self.ssh_user)

            return ssh
        except UserWarning:
            k = input(f'Unknown key for host {self.ssh_host}. Continue anyway? (Y/N) ')

            if k[0].upper() == 'Y':
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            else:
                return None
        except paramiko.BadHostKeyException as e:
            logger.critical('Can\'t connect to the server.')
            logger.critical(e)

            return None
        except paramiko.SSHException:
            pass

        try:
            ssh.connect(self.ssh_host, username=self.ssh_user)

            return ssh
        except paramiko.SSHException:
            pass

        if self.ssh_keyfile is None:
            try:
                password = getpass(f'{self.ssh_user}@{self.ssh_host}\'s password: ')
                ssh.connect(self.ssh_host, username=self.ssh_user, password=password)

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
            ssh.connect(self.ssh_host, username=self.ssh_user, pkey=pkey)
        except paramiko.SSHException:
            logger.critical('SSH connection to server failed')

            return None

        return ssh

    def _returncode_log(self, returncode):
        match returncode:
            case 2:
                logger.error('Rsync error (return code 2) - Protocol incompatibility')
            case 3:
                logger.error('Rsync error (return code 3) - Errors selecting input/output files, dirs')
            case 4:
                logger.error('Rsync error (return code 4) - Requested action not supported')
            case 5:
                logger.error('Rsync error (return code 5) - Error starting client-server protocol')
            case 10:
                logger.error('Rsync error (return code 10) - Error in socket I/O')
            case 11:
                logger.error('Rsync error (return code 11) - Error in file I/O')
            case 12:
                logger.error('Rsync error (return code 12) - Error in rsync protocol data stream')
            case 22:
                logger.error('Rsync error (return code 22) - Error allocating core memory buffers')
            case 23:
                logger.warning('Rsync error (return code 23) - Partial transfer due to error')
            case 24:
                logger.warning('Rsync error (return code 24) - Partial transfer due to vanished source files')
            case 30:
                logger.error('Rsync error (return code 30) - Timeout in data send/receive')
            case 35:
                logger.error('Rsync error (return code 35) - Timeout waiting for daemon connection')
            case _:
                logger.error('Rsync error (return code %d) - Check rsync(1) for details', returncode)

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
        count = 0

        with open(self._inputs_path, 'w', encoding='utf-8') as fp:
            for i in self.inputs:
                if not os.path.exists(i):
                    logger.warning('Input %s not found. Skipping', i)
                else:
                    fp.write(i)
                    fp.write('\n')
                    count += 1

        if count == 0:
            logger.info('No existing files or directories specified for backup. Nothing to do')

            try:
                notify('Backup finished. No files copied')
            except NameError:
                pass

            return 1

        _, self._exclude_path = mkstemp(prefix='tmp_exclude', text=True)

        with open(self._exclude_path, 'w', encoding='utf-8') as fp:
            if self.exclude is not None:
                for e in self.exclude:
                    fp.write(e)
                    fp.write('\n')

        if self.keep != -1 and self._remove_before:
            self.remove_old_backups()

        logger.info('Copying files. This may take a long time...')

        if self._last_backup == '':
            rsync = f'/usr/bin/rsync {self.options} --exclude-from={self._exclude_path} ' +\
                    f'--files-from={self._inputs_path} / "{self._server}{self._output_dir}"'
        else:
            rsync = f'/usr/bin/rsync {self.options} --link-dest="{self._last_backup}" --exclude-from=' +\
                    f'{self._exclude_path} --files-from={self._inputs_path} / "{self._server}{self._output_dir}"'

        euid = os.geteuid()

        if euid == 0 and self.ssh_keyfile is not None:
            rsync = f'{rsync} -e \'ssh -i {self.ssh_keyfile} -o StrictHostKeyChecking=no\''
        elif self._password_auth and which('sshpass'):
            rsync = f'{rsync} -e \'sshpass -e ssh -l {self.ssh_user} -o StrictHostKeyChecking=no\''
        else:
            rsync = f'{rsync} -e \'ssh -o StrictHostKeyChecking=no\''

        if self._remote and self.remote_sudo:
            rsync = f'{rsync} --rsync-path="sudo rsync"'

        args = shlex.split(rsync)

        with Popen(args, stdin=PIPE, stdout=PIPE, stderr=STDOUT, shell=False) as p:
            output, _ = p.communicate()

            try:
                del os.environ['SSHPASS']
            except KeyError:
                pass

            returncode = p.returncode

        output = output.decode("utf-8").split('\n')

        if returncode == 0:
            if self._verbose:
                logger.info('rsync: %s', output)
            else:
                logger.info('rsync: %s', output[-3])
                logger.info('rsync: %s', output[-2])
        else:
            self._returncode_log(returncode)

            if self._verbose:
                if returncode in [23, 24]:
                    logger.warning(output)
                else:
                    logger.error(output)

        if self.keep != -1 and not self._remove_before:
            self.remove_old_backups()

        os.remove(self._inputs_path)
        os.remove(self._exclude_path)

        if self._remote:
            _, stdout, _ = self._ssh.exec_command(f'if [ -d "{self._output_dir}" ]; then echo "ok"; fi')

            output = stdout.read().decode('utf-8').strip()

            if output == 'ok':
                logger.info('Backup completed')

                try:
                    _notify('Backup completed')
                except NameError:
                    pass
            else:
                logger.error('Backup failed')

                try:
                    _notify('Backup failed (check log for details)')
                except NameError:
                    pass

            if self._ssh:
                self._ssh.close()
        else:
            if returncode != 0:
                logger.error('Some errors occurred while performing the backup')

                try:
                    _notify('Some errors occurred while performing the backup. Check log for details')
                except NameError:
                    pass

                return 4

            logger.info('Backup completed')

            try:
                _notify('Backup completed')
            except NameError:
                pass

            return 0


def _parse_arguments():
    euid = os.geteuid()

    if euid == 0:
        user = os.getenv('SUDO_USER')
    else:
        user = os.getenv('USER')
    
    homedir = os.path.expanduser(f'~{user}')

    parser = argparse.ArgumentParser(prog='simple_backup',
                                     description='Simple backup script written in Python that uses rsync to copy files',
                                     epilog='See simple_backup(1) manpage for full documentation',
                                     formatter_class=MyFormatter)

    parser.add_argument('-v', '--verbose', action='store_true', help='More verbose output')
    parser.add_argument('-c', '--config', default=f'{homedir}/.config/simple_backup/simple_backup.conf',
                        help='Specify location of configuration file')
    parser.add_argument('-i', '--inputs', nargs='+', help='Paths/files to backup')
    parser.add_argument('-o', '--output', help='Output directory for the backup')
    parser.add_argument('-e', '--exclude', nargs='+', help='Files/directories/patterns to exclude from the backup')
    parser.add_argument('-k', '--keep', type=int, help='Number of old backups to keep')
    parser.add_argument('-u', '--user', help='Explicitly specify the user running the backup')
    parser.add_argument('-s', '--checksum', action='store_true', help='Use checksum rsync option to compare files')
    parser.add_argument('--ssh-host', help='Server hostname (for remote backup)')
    parser.add_argument('--ssh-user', help='Username to connect to server (for remote backup)')
    parser.add_argument('--keyfile', help='SSH key location')
    parser.add_argument('-z', '--compress', action='store_true', help='Compress data during the transfer')
    parser.add_argument('--remove-before-backup', action='store_true',
                        help='Remove old backups before executing the backup, instead of after')
    parser.add_argument('--no-syslog', action='store_true', help='Disable systemd journal logging')
    parser.add_argument('--rsync-options', nargs='+',
                        choices=['a', 'l', 'p', 't', 'g', 'o', 'c', 'h', 's', 'D', 'H', 'X'],
                        help='Specify options for rsync')
    parser.add_argument('--remote-sudo', action='store_true', help='Run rsync on remote server with sudo if allowed')
    parser.add_argument('--numeric-ids', action='store_true',
                        help='Use rsync \'--numeric-ids\' option (don\'t map uid/gid values by name)')

    args = parser.parse_args()

    return args


def _expand_inputs(inputs, user=None):
    expanded_inputs = []

    for i in inputs:
        if i == '':
            continue

        if user is not None:
            i_ex = glob(os.path.expanduser(i.replace('~', f'~{user}')))
        else:
            i_ex = glob(i)

            if '~' in i:
                logger.warning('Cannot expand \'~\'. No user specified')

        if len(i_ex) == 0:
            logger.warning('No file or directory matching input %s. Skipping...', i)
        else:
            expanded_inputs.extend(i_ex)

    return expanded_inputs


def _read_config(config_file, user=None):
    config_args = {'inputs': None,
                   'output': None,
                   'exclude': None,
                   'keep': -1,
                   'ssh_host': None,
                   'ssh_user': None,
                   'ssh_keyfile': None,
                   'remote_sudo': False,
                   'numeric_ids': False}

    if not os.path.isfile(config_file):
        logger.warning('Config file %s does not exist', config_file)

        return config_args

    config = configparser.ConfigParser()
    config.read(config_file)

    section = 'backup'

    # Allow compatibility with previous version of config file
    try:
        inputs = config.get(section, 'inputs')
    except configparser.NoSectionError:
        section = 'default'
        inputs = config.get(section, 'inputs')

    inputs = inputs.split(',')
    inputs = _expand_inputs(inputs, user)
    inputs = list(set(inputs))

    config_args['inputs'] = inputs

    output = config.get(section, 'backup_dir')

    if user is not None:
        output = os.path.expanduser(output.replace('~', f'~{user}'))
    elif user is None and '~' in output:
        logger.warning('Cannot expand \'~\', no user specified')

    config_args['output'] = output

    try:
        exclude = config.get(section, 'exclude')
        exclude = exclude.split(',')
    except configparser.NoOptionError:
        exclude = []

    config_args['exclude'] = exclude

    try:
        keep = config.getint(section, 'keep')
    except configparser.NoOptionError:
        keep = -1

    config_args['keep'] = keep

    try:
        ssh_host = config.get('server', 'ssh_host')
        ssh_user = config.get('server', 'ssh_user')
    except (configparser.NoSectionError, configparser.NoOptionError):
        ssh_host = None
        ssh_user = None

    config_args['ssh_host'] = ssh_host
    config_args['ssh_user'] = ssh_user

    try:
        ssh_keyfile = config.get('server', 'ssh_keyfile')
    except (configparser.NoSectionError, configparser.NoOptionError):
        ssh_keyfile = None

    config_args['ssh_keyfile'] = ssh_keyfile

    try:
        remote_sudo = config.getboolean('server', 'remote_sudo')
    except (configparser.NoSectionError, configparser.NoOptionError):
        remote_sudo = False

    config_args['remote_sudo'] = remote_sudo

    try:
        numeric_ids = config.getboolean('server', 'numeric_ids')
    except (configparser.NoSectionError, configparser.NoOptionError):
        numeric_ids = False

    config_args['numeric_ids'] = numeric_ids

    return config_args


def _notify(text):
    euid = os.geteuid()

    if euid == 0:
        uid = os.getenv('SUDO_UID')
    else:
        uid = euid

    if uid is None:
        return

    os.seteuid(int(uid))
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'

    obj = dbus.SessionBus().get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
    obj = dbus.Interface(obj, 'org.freedesktop.Notifications')
    obj.Notify('', 0, '', 'simple_backup', text, [], {'urgency': 1}, 10000)

    os.seteuid(int(euid))


def simple_backup():
    """Main"""

    args = _parse_arguments()

    if args.user:
        user = args.user
        homedir = os.path.expanduser(f'~{user}')
    else:
        euid = os.geteuid()

        if euid == 0:
            user = os.getenv('SUDO_USER')
            homedir = os.path.expanduser(f'~{user}')
        else:
            user = os.getenv('USER')
            homedir = os.getenv('HOME')

    if homedir is None:
        homedir = ''

    if args.no_syslog:
        try:
            logger.removeHandler(j_handler)
        except NameError:
            pass

    try:
        config_args = _read_config(args.config, user)
    except (configparser.NoSectionError, configparser.NoOptionError):
        logger.critical('Bad configuration file')
        return 6

    inputs = args.inputs if args.inputs is not None else config_args['inputs']
    output = args.output if args.output is not None else config_args['output']
    exclude = args.exclude if args.exclude is not None else config_args['exclude']
    keep = args.keep if args.keep is not None else config_args['keep']
    ssh_host = args.ssh_host if args.ssh_host is not None else config_args['ssh_host']
    ssh_user = args.ssh_user if args.ssh_user is not None else config_args['ssh_user']
    ssh_keyfile = args.keyfile if args.keyfile is not None else config_args['ssh_keyfile']
    remote_sudo = args.remote_sudo or config_args['remote_sudo']

    if args.rsync_options is None:
        rsync_options = ['-a', '-r', '-v', '-h', '-H', '-X', '-s', '--ignore-missing-args', '--mkpath']
    else:
        rsync_options = ['-r', '-v']

        for ro in args.rsync_options:
            rsync_options.append(f'-{ro}')

    if args.checksum:
        rsync_options.append('-c')

    if args.compress:
        rsync_options.append('-z')

    if args.numeric_ids or config_args['numeric_ids']:
        rsync_options.append('--numeric-ids')

    rsync_options = ' '.join(rsync_options)

    backup = Backup(inputs, output, exclude, keep, rsync_options, ssh_host, ssh_user, ssh_keyfile,
                    remote_sudo, remove_before=args.remove_before_backup, verbose=args.verbose)

    return_code = backup.check_params(homedir)

    if return_code == 0:
        return backup.run()

    return return_code


if __name__ == '__main__':
    simple_backup()
