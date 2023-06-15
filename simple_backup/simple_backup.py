#!/usr/bin/python3

# Import libraries
import sys
import os
from functools import wraps
from shutil import rmtree
import argparse
import configparser
import logging
from logging import StreamHandler
from timeit import default_timer
from subprocess import Popen, PIPE, STDOUT
from datetime import datetime
from tempfile import mkstemp
from glob import glob

from dotenv import load_dotenv

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
    user = os.getenv('USER')
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
    pass


class Backup:

    def __init__(self, inputs, output, exclude, keep, options, remove_before=False):
        self.inputs = inputs
        self.output = output
        self.exclude = exclude
        self.options = options
        self.keep = keep
        self.remove_before = remove_before
        self._last_backup = ''
        self._output_dir = ''
        self._inputs_path = ''
        self._exclude_path = ''
        self._err_flag = False

    def check_params(self):
        if self.inputs is None or len(self.inputs) == 0:
            logger.info('No existing files or directories specified for backup. Nothing to do')

            return 1

        if self.output is None:
            logger.critical('No output path specified. Use -o argument or specify output path in configuration file')

            return 2

        if not os.path.isdir(self.output):
            logger.critical('Output path for backup does not exist')

            return 2

        self.output = os.path.abspath(self.output)

        if self.keep is None:
            self.keep = -1

        return 0

    # Function to create the actual backup directory
    def create_backup_dir(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._output_dir = f'{self.output}/simple_backup/{now}'

        os.makedirs(self._output_dir, exist_ok=True)

    def remove_old_backups(self):
        try:
            dirs = os.listdir(f'{self.output}/simple_backup')
        except FileNotFoundError:
            return

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
                    logger.error(f'Error while removing backup {dirs[i]}. Directory not found')
                except PermissionError:
                    logger.error(f'Error while removing backup {dirs[i]}. Permission denied')

            if count == 1:
                logger.info(f'Removed {count} backup')
            else:
                logger.info(f'Removed {count} backups')

    def find_last_backup(self):
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

    # Function to read configuration file
    @timing(logger)
    def run(self):
        logger.info('Starting backup...')

        try:
            notify('Starting backup...')
        except NameError:
            pass

        self.find_last_backup()
        self.create_backup_dir()

        _, self._inputs_path = mkstemp(prefix='tmp_inputs', text=True)
        count = 0

        with open(self._inputs_path, 'w') as fp:
            for i in self.inputs:
                if not os.path.exists(i):
                    logger.warning(f'Input {i} not found. Skipping')
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

        with open(self._exclude_path, 'w') as fp:
            if self.exclude is not None:
                for e in self.exclude:
                    fp.write(e)
                    fp.write('\n')

        if self.keep != -1 and self.remove_before:
            self.remove_old_backups()

        logger.info('Copying files. This may take a long time...')

        if self._last_backup == '':
            rsync = f'rsync {self.options} --exclude-from={self._exclude_path} ' +\
                    f'--files-from={self._inputs_path} / "{self._output_dir}" ' +\
                    '--ignore-missing-args'
        else:
            rsync = f'rsync {self.options} --link-dest="{self._last_backup}" --exclude-from=' +\
                    f'{self._exclude_path} --files-from={self._inputs_path} / "{self._output_dir}" ' +\
                    '--ignore-missing-args'

        p = Popen(rsync, stdout=PIPE, stderr=STDOUT, shell=True)
        output, _ = p.communicate()

        if p.returncode != 0:
            self._err_flag = True

        output = output.decode("utf-8").split('\n')

        logger.info(f'rsync: {output[-3]}')
        logger.info(f'rsync: {output[-2]}')

        if self.keep != -1 and not self.remove_before:
            self.remove_old_backups()

        os.remove(self._inputs_path)
        os.remove(self._exclude_path)

        logger.info('Backup completed')

        if self._err_flag:
            logger.warning('Some errors occurred (check log for details)')

            try:
                notify('Backup finished with errors (check log for details)')
            except NameError:
                pass

            return 4
        else:
            try:
                notify('Backup finished')
            except NameError:
                pass

            return 0


def _parse_arguments():
    parser = argparse.ArgumentParser(prog='simple_backup',
                                     description='Simple backup script written in Python that uses rsync to copy files',
                                     epilog='Report bugs to dfucini<at>gmail<dot>com',
                                     formatter_class=MyFormatter)

    parser.add_argument('-c', '--config', default=f'{homedir}/.config/simple_backup/simple_backup.conf',
                        help='Specify location of configuration file')
    parser.add_argument('-i', '--input', nargs='+', help='Paths/files to backup')
    parser.add_argument('-o', '--output', help='Output directory for the backup')
    parser.add_argument('-e', '--exclude', nargs='+', help='Files/directories/patterns to exclude from the backup')
    parser.add_argument('-k', '--keep', type=int, help='Number of old backups to keep')
    parser.add_argument('-s', '--checksum', action='store_true',
                        help='Use checksum rsync option to compare files (MUCH SLOWER)')
    parser.add_argument('--remove-before-backup', action='store_true',
                        help='Remove old backups before executing the backup, instead of after')
    parser.add_argument('--no-syslog', action='store_true', help='Disable systemd journal logging')
    parser.add_argument('--rsync-options', nargs='+',
                        choices=['a', 'l', 'p', 't', 'g', 'o', 'c', 'h', 'D', 'H', 'X'],
                        help='Specify options for rsync')

    args = parser.parse_args()

    return args


def _expand_inputs(inputs):
    expanded_inputs = []

    for i in inputs:
        if i == '':
            continue

        i_ex = glob(os.path.expanduser(i.replace('~', f'~{user}')))

        if len(i_ex) == 0:
            logger.warning(f'No file or directory matching input {i}. Skipping...')
        else:
            expanded_inputs.extend(i_ex)

    return expanded_inputs


def _read_config(config_file):
    if not os.path.isfile(config_file):
        logger.warning(f'Config file {config_file} does not exist')

        return None, None, None, None

    config = configparser.ConfigParser()
    config.read(config_file)

    inputs = config.get('default', 'inputs')
    inputs = inputs.split(',')
    inputs = _expand_inputs(inputs)
    inputs = list(set(inputs))
    output = config.get('default', 'backup_dir')
    output = os.path.expanduser(output.replace('~', f'~{user}'))
    exclude = config.get('default', 'exclude')
    exclude = exclude.split(',')
    keep = config.getint('default', 'keep')

    return inputs, output, exclude, keep


def notify(text):
    euid = os.geteuid()

    if euid == 0:
        uid = os.getenv('SUDO_UID')
    else:
        uid = os.geteuid()

    os.seteuid(int(uid))
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'

    obj = dbus.SessionBus().get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
    obj = dbus.Interface(obj, 'org.freedesktop.Notifications')
    obj.Notify('', 0, '', 'simple_backup', text, [], {'urgency': 1}, 10000)

    os.seteuid(int(euid))


def simple_backup():
    args = _parse_arguments()

    if args.no_syslog:
        try:
            logger.removeHandler(j_handler)
        except NameError:
            pass

    inputs, output, exclude, keep = _read_config(args.config)

    if args.input is not None:
        inputs = args.input

    if args.output is not None:
        output = args.output

    if args.exclude is not None:
        exclude = args.exclude

    if args.keep is not None:
        keep = args.keep

    if args.rsync_options is None:
        if args.checksum:
            rsync_options = '-arcvh -H -X'
        else:
            rsync_options = '-arvh -H -X'
    else:
        rsync_options = '-r -v '

        for ro in args.rsync_options:
            rsync_options = rsync_options + f'-{ro} '

        if '-c ' not in rsync_options and args.checksum:
            rsync_options = rsync_options + '-c'

    backup = Backup(inputs, output, exclude, keep, rsync_options, remove_before=args.remove_before_backup)

    return_code = backup.check_params()

    if return_code == 0:
        return backup.run()

    return return_code


if __name__ == '__main__':
    simple_backup()
