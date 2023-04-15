#!/usr/bin/python3

# Import libraries
from dotenv import load_dotenv
import os
from shutil import rmtree
import argparse
import configparser
import logging
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from subprocess import Popen, PIPE, STDOUT
from datetime import datetime
from tempfile import mkstemp


class MyFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


class Backup:

    def __init__(self, inputs, output, exclude, keep, options):
        self.inputs = inputs
        self.output = output
        self.exclude = exclude
        self.options = options
        self.keep = keep
        self._last_backup = ''
        self._output_dir = ''
        self._inputs_path = ''
        self._exclude_path = ''
        self._err_flag = False

    def check_params(self):
        if self.inputs is None or len(self.inputs) == 0:
            logger.info('No files or directory specified for backup.')

            return False

        for i in self.inputs:
            if os.path.islink(i):
                try:
                    i_new = os.readlink(i)
                    logger.info(f'Input {i} is a symbolic link referencing {i_new}. Copying {i_new} instead')
                    self.inputs.remove(i)
                    self.inputs.append(i_new)
                except Exception:
                    logger.warning(f'Input {i} is a link and cannot be read. Skipping')
                    self.inpts.remove(i)

        if not os.path.isdir(self.output):
            logger.critical('Output path for backup does not exist')

            return False

        if self.keep is None:
            self.keep = -1

        return True

    # Function to create the actual backup directory
    def create_backup_dir(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._output_dir = f'{self.output}/simple_backup/{now}'

        os.makedirs(self._output_dir, exist_ok=True)

    def remove_old_backups(self):
        try:
            dirs = os.listdir(f'{self.output}/simple_backup')
        except Exception:
            logger.info('No older backups to remove')

            return

        if dirs.count('last_backup') > 0:
            dirs.remove('last_backup')

        n_backup = len(dirs) - 1

        if n_backup > self.keep:
            logger.info('Removing old backups...')
            dirs.sort()

            for i in range(n_backup - self.keep):
                try:
                    rmtree(f'{self.output}/simple_backup/{dirs[i]}')
                except Exception:
                    logger.error(f'Error while removing backup {dirs[i]}')

    def find_last_backup(self):
        if os.path.islink(f'{self.output}/simple_backup/last_backup'):
            try:
                self._last_backup = os.readlink(f'{self.output}/simple_backup/last_backup')
            except Exception:
                logger.error('Previous backup could not be read')

    # Function to read configuration file
    def run(self):
        logger.info('Starting backup...')

        self.create_backup_dir()
        self.find_last_backup()

        if os.path.islink(f'{self.output}/simple_backup/last_backup'):
            try:
                os.remove(f'{self.output}/simple_backup/last_backup')
            except Exception:
                logger.error('Failed to remove last_backup link')
                self._err_flag = True

        inputs_handle, self._inputs_path = mkstemp(prefix='tmp_inputs', text=True)
        exclude_handle, self._exclude_path = mkstemp(prefix='tmp_exclude', text=True)

        with open(self._inputs_path, 'w') as fp:
            for i in self.inputs:
                if not os.path.exists(i):
                    logger.warning(f'Input {i} not found. Skipping')
                else:
                    fp.write(i)
                    fp.write('\n')

        with open(self._exclude_path, 'w') as fp:
            for e in self.exclude:
                fp.write(e)
                fp.write('\n')

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

        logger.info(f'Output of rsync command: {output.decode("utf-8")}')

        try:
            os.symlink(self._output_dir, f'{self.output}/simple_backup/last_backup')
        except Exception:
            logger.error('Failed to create last_backup link')
            self._err_flag = True

        if self.keep != -1:
            self.remove_old_backups()

        os.remove(self._inputs_path)
        os.remove(self._exclude_path)

        logger.info('Backup completed')

        if self._err_flag:
            logger.warning('Some errors occurred (check log for details)')


load_dotenv()
euid = os.geteuid()

if euid == 0:
    user = os.getenv("SUDO_USER")
    homedir = os.path.expanduser(f'~{user}')
else:
    homedir = os.getenv('HOME')

logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(os.path.basename(__file__))
c_handler = StreamHandler()

try:
    f_handler = RotatingFileHandler(f'{homedir}/.simple_backup/simple_backup.log', maxBytes=1024000, backupCount=5)
except Exception:
    f_handler = None

c_handler.setLevel(logging.INFO)
c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
logger.addHandler(c_handler)

if f_handler:
    f_handler.setLevel(logging.INFO)
    f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    f_handler.setFormatter(f_format)
    logger.addHandler(f_handler)


def _parse_arguments():
    parser = argparse.ArgumentParser(prog='simple_backup',
                                     description='A simple backup script written in Python that uses rsync to copy files',
                                     epilog='Report bugs to dfucini<at>gmail<dot>com',
                                     formatter_class=MyFormatter)

    parser.add_argument('-c', '--config', default=f'{homedir}/.simple_backup/simple_backup.config',
                        help='Specify location of configuration file')
    parser.add_argument('-i', '--input', nargs='+', help='Paths/files to backup')
    parser.add_argument('-o', '--output', help='Output directory for the backup')
    parser.add_argument('-e', '--exclude', nargs='+', help='Files/directories/patterns to exclude from the backup')
    parser.add_argument('-k', '--keep', type=int, help='Number of old backups to keep')
    parser.add_argument('-s', '--checksum', action='store_true',
                        help='Use checksum rsync option to compare files (MUCH SLOWER)')

    args = parser.parse_args()

    return args


def _read_config(config_file):
    if not os.path.isfile(config_file):
        logger.warning(f'Config file {config_file} does not exist')

        return None, None, None, None

    config = configparser.ConfigParser()
    config.read(config_file)

    inputs = config.get('default', 'inputs')
    inputs = inputs.split(',')
    output = config.get('default', 'backup_dir')
    exclude = config.get('default', 'exclude')
    exclude = exclude.split(',')
    keep = config.getint('default', 'keep')

    return inputs, output, exclude, keep


def simple_backup():
    args = _parse_arguments()
    inputs, output, exclude, keep = _read_config(args.config)

    if args.input is not None:
        inputs = args.input

    if args.output is not None:
        output = args.output

    if args.exclude is not None:
        exclude = args.exclude

    if args.keep is not None:
        keep = args.keep

    if args.checksum:
        backup_options = '-arcvh -H -X'
    else:
        backup_options = '-arvh -H -X'

    backup = Backup(inputs, output, exclude, keep, backup_options)

    if backup.check_params():
        backup.run()


if __name__ == '__main__':
    simple_backup()
