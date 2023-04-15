#!/usr/bin/python3

# Import libraries
from sys import exit, argv

import os
from os.path import expanduser, isfile, isdir, islink, exists, abspath
from shutil import move, rmtree

import subprocess

from datetime import datetime
from tempfile import mkstemp


class Backup:

    def __init__(self, *args, **kwargs):
        super(Backup, self).__init__(*args, **kwargs)

        self.log_path = ''
        self.logfile = None
        self.err_path = ''
        self.errfile = None
        self.warn_path = ''
        self.warnfile = None
        self.homedir = ''
        self.backup_dev = ''
        self.backup_dir = ''
        self.last_backup = ''
        self.inputs = ''
        self.inputs_path = ''
        self.exclude_path = ''
        self.exclude = ''
        self.options = ''
        self.keep = -1
        self.n_in = 0

    # Help function
    @staticmethod
    def help_function():
        print('simple_backup, version 2.0.0')
        print('')
        print('Usage: {} [OPTIONS]'.format(argv[0]))
        print('')
        print('Options:')
        print('-h, --help                             Print this help and exit.')
        print('-c, --config      CONFIG_FILE          Use the specified configuration file')
        print('                                       instead of the default one.')
        print('                                       All other options are ignored.')
        print('-i, --input       INPUT [INPUT...]     Specify a file/dir to include in the backup.')
        print('-d, --directory   DIR                  Specify the output directory for the backup.')
        print('-e, --exclude     PATTERN [PATTERN...] Specify a file/dir/pattern to exclude from')
        print('                                       the backup.')
        print('-k, --keep        NUMBER               Specify the number of old backups to keep.')
        print('                                       Default: keep all.')
        print('-s, --checksum                         Use the checksum rsync option to compare files')
        print('                                       (MUCH slower).')
        print('')
        print('If no option is given, the program uses the default')
        print('configuration file: $HOMEDIR/.simple_backup/config.')
        print('')
        print('Report bugs to dfucini@gmail.com')

        exit(0)

    # Function to read configuration file
    def read_conf(self, config=None):
        if config is None:
            config = self.homedir + '/.simple_backup/config'

            if not isfile(config):
                # If default config file doesn't exist, exit
                log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
                self.logfile.write(log_message)
                self.logfile.write('\n')
                print('Backup failed')
                err_message = 'Error: Configuration file not found'
                print(err_message)
                self.errfile.write(err_message)
                self.errfile.write('\n')

                self.logfile.close()
                self.errfile.close()
                self.warnfile.close()

                try:
                    move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                    move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                except Exception:
                    print('Failed to create logs in {}'.format(self.homedir))

                try:
                    os.remove(self.warn_path)
                except Exception:
                    print('Failed to remove temporary file')

                exit(1)
        else:
            if not isfile(config):
                # If the provided configuration file doesn't exist, exit
                log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
                self.logfile.write(log_message)
                self.logfile.write('\n')
                print('Backup failed')
                err_message = 'Error: Configuration file not found'
                print(err_message)
                self.errfile.write(err_message)
                self.errfile.write('\n')

                self.logfile.close()
                self.errfile.close()
                self.warnfile.close()

                try:
                    move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                    move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                except Exception:
                    print('Failed to create logs in {}'.format(self.homedir))

                try:
                    os.remove(self.warn_path)
                except Exception:
                    print('Failed to remove temporary file')

                exit(1)

        # Create temporary files
        inputs_handle, self.inputs_path = mkstemp(prefix='tmp_inputs', text=True)
        exclude_handle, self.exclude_path = mkstemp(prefix='tmp_exclude', text=True)

        # Open temporary files
        self.inputs = open(self.inputs_path, 'w')
        self.exclude = open(self.exclude_path, 'w')

        # Parse the configuration file
        with open(config, 'r') as fp:
            line = fp.readline()

            while line:
                if line[:7] == 'inputs=':
                    line = line[7:].rstrip()
                    input_values = line.split(',')
                    for i in input_values:
                        if not exists(i):
                            warn_message = 'Warning: input "' + i + '" not found. Skipping'
                            print(warn_message)
                            self.warnfile.write(warn_message)
                            self.warnfile.write('\n')
                        else:
                            self.inputs.write(i)
                            self.inputs.write('\n')
                            self.n_in = self.n_in + 1
                elif line[:11] == 'backup_dir=':
                    line = line[11:].rstrip()
                    self.backup_dev = line
                elif line[:8] == 'exclude=':
                    line = line[8:].rstrip()
                    exclude_values = line.split(',')
                    for i in exclude_values:
                        self.exclude.write(i)
                        self.exclude.write('\n')
                elif line[:5] == 'keep=':
                    line = line[5:].rstrip()
                    self.keep = int(line)

                line = fp.readline()

            fp.close()
            self.inputs.close()
            self.exclude.close()

        # If the backup directory is not set or doesn't exist, exit
        if self.backup_dev == '' or not isdir(self.backup_dev):
            log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
            self.logfile.write(log_message)
            self.logfile.write('\n')
            print('Backup failed')
            err_message = 'Error: Output folder "' + self.backup_dev + '" not found'
            print(err_message)
            self.errfile.write(err_message)
            self.errfile.write('\n')

            self.logfile.close()
            self.errfile.close()
            self.warnfile.close()

            try:
                move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                move(self.err_path, self.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to create logs in {}'.format(self.homedir))

            try:
                os.remove(self.warn_path)
                os.remove(self.inputs_path)
                os.remove(self.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            exit(1)

        self.backup_dir = self.backup_dev + '/simple_backup'
        date = str(datetime.now())

        # Create the backup subdirectory using date
        if isdir(self.backup_dir):
            # If previous backups exist, save link to the last backup
            self.last_backup = self.backup_dir + '/last_backup'
            if islink(self.last_backup):
                try:
                    self.last_backup = os.readlink(self.last_backup)
                except Exception:
                    self.last_backup = ''
                    err_message = 'An error occurred when reading the last_backup link. Continuing anyway'
                    print(err_message)
                    self.errfile.write(err_message)
                    self.errfile.write('\n')

            else:
                self.last_backup = ''

        self.backup_dir = self.backup_dir + '/' + date

        try:
            os.makedirs(self.backup_dir)
        except PermissionError as e:
            log_message = str(datetime.now()) + 'Backup failed (see errors.log)'
            self.logfile.write(log_message)
            self.logfile.write('\n')
            print('Backup failed')
            print(str(e))
            self.errfile.write(str(e))
            self.errfile.write('\n')

            self.logfile.close()
            self.errfile.close()
            self.warnfile.close()

            try:
                move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                move(self.err_path, self.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to create logs in {}'.format(self.homedir))

            try:
                os.remove(self.warn_path)
                os.remove(self.inputs_path)
                os.remove(self.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            exit(1)
        except Exception:
            log_message = str(datetime.now()) + 'Backup failed (see errors.log)'
            self.logfile.write(log_message)
            self.logfile.write('\n')
            print(log_message)
            err_message = 'Failed to create backup directory'
            self.errfile.write(err_message)
            self.errfile.write('\n')

            self.logfile.close()
            self.errfile.close()
            self.warnfile.close()

            try:
                move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                move(self.err_path, self.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to create logs in {}'.format(self.homedir))

            try:
                os.remove(self.warn_path)
                os.remove(self.inputs_path)
                os.remove(self.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            exit(1)

    # Function to parse options
    def parse_options(self):
        # Create temporary files
        inputs_handle, self.inputs_path = mkstemp(prefix='tmp_inputs', text=True)
        exclude_handle, self.exclude_path = mkstemp(prefix='tmp_exclude', text=True)

        # Open temporary files
        self.inputs = open(self.inputs_path, 'w')
        self.exclude = open(self.exclude_path, 'w')

        i = 1
        while i < len(argv):
            var = argv[i]

            if var in ['-h', '--help']:
                self.help_function()
            elif var in ['-i', '--input']:
                val = argv[i+1]
                while i < len(argv) - 1 and val[0] != '-':
                    inp = val

                    if not exists(inp):
                        warn_message = 'Warning: input "' + inp + '" not found. Skipping'
                        print(warn_message)
                        self.warnfile.write(warn_message)
                        self.warnfile.write('\n')
                    else:
                        self.n_in = self.n_in + 1
                        self.inputs.write(inp)
                        self.inputs.write('\n')

                    i = i + 1
                    val = argv[i+1]
            elif var in ['-d', '--directory']:
                self.backup_dev = argv[i+1]
                self.backup_dev = abspath(self.backup_dev)

                if not exists(self.backup_dev) or not isdir(self.backup_dev):
                    log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
                    self.logfile.write(log_message)
                    self.logfile.write('\n')
                    print('Backup failed')
                    err_message = 'Error: output folder "' + self.backup_dev + '" not found'
                    print(err_message)
                    self.errfile.write(err_message)
                    self.errfile.write('\n')

                    self.logfile.close()
                    self.errfile.close()
                    self.warnfile.close()
                    self.inputs.close()
                    self.exclude.close()

                    try:
                        move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                        move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                    except Exception:
                        print('Failed to create logs in {}'.format(self.homedir))

                    try:
                        os.remove(self.warn_path)
                        os.remove(self.inputs_path)
                        os.remove(self.exclude_path)
                    except Exception:
                        print('Failed to remove temporary files')

                    exit(1)

                self.backup_dir = self.backup_dev + '/simple_backup'
                date = str(datetime.now())

                # Create the backup subdirectory using date
                if isdir(self.backup_dir):
                    # If previous backups exist, save link to the last backup
                    self.last_backup = self.backup_dir + '/last_backup'
                    if islink(self.last_backup):
                        try:
                            self.last_backup = os.readlink(self.last_backup)
                        except Exception:
                            self.last_backup = ''
                            err_message = 'An error occurred when reading the last_backup link. Continuing anyway'
                            print(err_message)
                            self.errfile.write(err_message)
                            self.errfile.write('\n')

                    else:
                        self.last_backup = ''

                self.backup_dir = self.backup_dir + '/' + date

                try:
                    os.makedirs(self.backup_dir)
                except PermissionError as e:
                    log_message = str(datetime.now()) + 'Backup failed (see errors.log)'
                    self.logfile.write(log_message)
                    self.logfile.write('\n')
                    print('Backup failed')
                    print(str(e))
                    self.errfile.write(str(e))
                    self.errfile.write('\n')

                    self.logfile.close()
                    self.errfile.close()
                    self.warnfile.close()
                    self.inputs.close()
                    self.exclude.close()

                    try:
                        move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                        move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                    except Exception:
                        print('Failed to create logs in {}'.format(self.homedir))

                    try:
                        os.remove(self.warn_path)
                        os.remove(self.inputs_path)
                        os.remove(self.exclude_path)
                    except Exception:
                        print('Failed to remove temporary files')

                    exit(1)
                except Exception:
                    log_message = str(datetime.now()) + 'Backup failed (see errors.log)'
                    self.logfile.write(log_message)
                    self.logfile.write('\n')
                    print('Backup failed')
                    err_message = 'Failed to create backup directory'
                    print(err_message)
                    self.errfile.write(err_message)
                    self.errfile.write('\n')

                    self.logfile.close()
                    self.errfile.close()
                    self.warnfile.close()
                    self.inputs.close()
                    self.exclude.close()

                    try:
                        move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                        move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                    except Exception:
                        print('Failed to create logs in {}'.format(self.homedir))

                    try:
                        os.remove(self.warn_path)
                        os.remove(self.inputs_path)
                        os.remove(self.exclude_path)
                    except Exception:
                        print('Failed to remove temporary files')

                    exit(1)

                i = i + 1
            elif var in ['-e', '--exclude']:
                val = argv[i+1]
                while i < len(argv) - 1 and val[0] != '-':
                    exc = val
                    self.exclude.write(exc)
                    self.exclude.write('\n')

                    i = i + 1
                    val = argv[i+1]
            elif var in ['-k', '--keep']:
                self.keep = int(argv[i+1])

                i = i + 1
            elif var in ['-c', '--config']:
                self.read_conf(argv[i+1])

                i = i + 1
            elif var in ['-s', '--checksum']:
                self.options = '-arcvh -H -X'
            else:
                log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
                self.logfile.write(log_message)
                self.logfile.write('\n')
                print('Backup failed')
                err_message = 'Error: Option "' + var +\
                              '" not recognised. Use "simple-backup -h" to see available options'
                print(err_message)
                self.errfile.write(err_message)
                self.errfile.write('\n')

                self.logfile.close()
                self.errfile.close()
                self.warnfile.close()
                self.inputs.close()
                self.exclude.close()

                try:
                    move(self.log_path, self.homedir + '/.simple_backup/simple_backup.log')
                    move(self.err_path, self.homedir + '/.simple_backup/errors.log')
                except Exception:
                    print('Failed to create logs in {}'.format(self.homedir))

                try:
                    os.remove(self.warn_path)
                    os.remove(self.inputs_path)
                    os.remove(self.exclude_path)
                except Exception:
                    print('Failed to remove temporary files')

                exit(1)

            i = i + 1

        self.inputs.close()
        self.exclude.close()

    def exec_(self):
        print('Copying files. This may take a long time...')

        if self.last_backup == '':
            rsync = 'rsync ' + self.options + ' --exclude-from=' + self.exclude_path +\
                    ' --files-from=' + self.inputs_path + ' / "' + self.backup_dir +\
                    '" --ignore-missing-args >> ' + self.log_path + ' 2>> ' + self.err_path
        else:
            rsync = 'rsync ' + self.options + ' --link-dest="' + self.last_backup + '" --exclude-from=' +\
                    self.exclude_path + ' --files-from=' + self.inputs_path + ' / "' + self.backup_dir +\
                    '" --ignore-missing-args >> ' + self.log_path + ' 2>> ' + self.err_path

        subprocess.run(rsync, shell=True)


def main():

    backup = Backup()

    # Create temporary log files
    log_handle, backup.log_path = mkstemp(prefix='tmp_log', text=True)
    err_handle, backup.err_path = mkstemp(prefix='tmp_err', text=True)
    warn_handle, backup.warn_path = mkstemp(prefix='tmp_warn', text=True)

    # Open log files
    backup.logfile = open(backup.log_path, 'w')
    backup.errfile = open(backup.err_path, 'w')
    backup.warnfile = open(backup.warn_path, 'w')

    # Set homedir and default options
    try:
        backup.homedir = '/home/' + os.environ['SUDO_USER']
    except Exception:
        backup.homedir = expanduser('~')

    backup.options = '-arvh -H -X'

    # Check number of parameters
    if len(argv) == 1:
        # If simple backup directory doesn't exist, create it and exit
        if not isdir(backup.homedir + '/.simple_backup'):
            try:
                os.mkdir(backup.homedir + '/.simple_backup')
                log_message = 'Created directory "' + backup.homedir + '/.simple_backup".\n' +\
                              'Copy there the sample configuration and edit it\n' +\
                              'to your needs before running the backup,\n' +\
                              'or pass options directly on the command line.'
                backup.logfile.write(log_message)
                backup.logfile.write('\n')
                print(log_message)

                backup.logfile.close()
                backup.errfile.close()
                backup.warnfile.close()

                try:
                    move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
                except Exception:
                    print('Failed to create logs in {}'.format(backup.homedir))

                try:
                    os.remove(backup.err_path)
                    os.remove(backup.warn_path)
                except Exception:
                    print('Failed to remove temporary files')
            except Exception:
                print('Failed to create .simple_backup directory in {}'.format(backup.homedir))

                backup.logfile.close()
                backup.errfile.close()
                backup.warnfile.close()

                try:
                    os.remove(backup.log_path)
                    os.remove(backup.err_path)
                    os.remove(backup.warn_path)
                except Exception:
                    print('Failed to remove temporary files')

            exit(1)

        # Read configuration file
        backup.read_conf()
    else:
        # Parse command line options
        backup.parse_options()

        if backup.n_in > 0 and (backup.backup_dir == '' or
                                not isdir(backup.backup_dir)):
            # If the backup directory is not set or doesn't exist, exit
            log_message = str(datetime.now()) + ': Backup failed (see errors.log)'
            backup.logfile.write(log_message)
            backup.logfile.write('\n')
            print('Backup failed')
            err_message = 'Error: Output folder "' + backup.backup_dev + '" not found'
            print(err_message)
            backup.errfile.write(err_message)
            backup.errfile.write('\n')

            backup.logfile.close()
            backup.errfile.close()
            backup.warnfile.close()

            try:
                move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
                move(backup.err_path, backup.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to create logs in {}'.format(backup.homedir))

            try:
                os.remove(backup.warn_path)
                os.remove(backup.inputs_path)
                os.remove(backup.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            exit(1)
        elif backup.n_in == 0 and backup.backup_dir == '':
            if not isdir(backup.homedir + '/.simple_backup'):
                try:
                    os.mkdir(backup.homedir + '/.simple_backup')
                    log_message = 'Created directory "' + backup.homedir + '/.simple_backup".\n' +\
                                  'Copy there the sample configuration and edit it\n' +\
                                  'to your needs before running the backup,\n' +\
                                  'or pass options directly on the command line.'
                    backup.logfile.write(log_message)
                    backup.logfile.write('\n')
                    print(log_message)

                    backup.logfile.close()
                    backup.errfile.close()
                    backup.warnfile.close()

                    try:
                        move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
                    except Exception:
                        print('Failed to create logs in {}'.format(backup.homedir))

                    try:
                        os.remove(backup.err_path)
                        os.remove(backup.warn_path)
                        os.remove(backup.inputs_path)
                        os.remove(backup.exclude_path)
                    except Exception:
                        print('Failed to remove temporary files')
                except Exception:
                    print('Failed to create .simple_backup directory in {}'.format(backup.homedir))

                    backup.logfile.close()
                    backup.errfile.close()
                    backup.warnfile.close()

                    try:
                        os.remove(backup.log_path)
                        os.remove(backup.err_path)
                        os.remove(backup.warn_path)
                        os.remove(backup.inputs_path)
                        os.remove(backup.exclude_path)
                    except Exception:
                        print('Failed to remove temporary files')

                exit(1)

            try:
                os.remove(backup.inputs_path)
                os.remove(backup.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            backup.read_conf(backup.homedir + '/.simple_backup/config')

    if backup.n_in == 0:
        log_message = str(datetime.now()) + ': Backup finished (no files copied)'
        backup.logfile.write(log_message)
        backup.logfile.write('\n')
        print('Backup finished (no files copied')
        warn_message = 'Warning: no valid input selected. Nothing to do'
        print(warn_message)
        backup.warnfile.write(warn_message)
        backup.warnfile.write('\n')

        backup.logfile.close()
        backup.errfile.close()
        backup.warnfile.close()

        try:
            move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
            move(backup.warn_path, backup.homedir + '/.simple_backup/warnings.log')
        except Exception:
            print('Failed to create logs in {}'.format(backup.homedir))

        try:
            os.remove(backup.err_path)
            os.remove(backup.inputs_path)
            os.remove(backup.exclude_path)
        except Exception:
            print('Failed to remove temporary files')

        exit(0)

    log_message = str(datetime.now()) + ': Starting backup'
    backup.logfile.write(log_message)
    backup.logfile.write('\n')
    print('Starting backup...')

    # If specified, keep the last n backups and remove the others. Default: keep all
    if backup.keep > -1:
        try:
            dirs = os.listdir(backup.backup_dev + '/simple_backup')
        except Exception:
            err_message = 'Failed to access backup directory'
            backup.errfile.write(err_message)
            backup.errfile.write('\n')
            print(err_message)

            backup.logfile.close()
            backup.errfile.close()
            backup.warnfile.close()

            try:
                move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
                move(backup.err_path, backup.homedir + '.simple_backup/errors.log')
            except Exception:
                print('Failed to create logs in {}'.format(backup.homedir))

            try:
                os.remove(backup.warn_path)
                os.remove(backup.inputs_path)
                os.remove(backup.exclude_path)
            except Exception:
                print('Failed to remove temporary files')

            exit(1)
        if dirs.count('last_backup') > 0:
            dirs.remove('last_backup')
        n_backup = len(dirs) - 1

        if n_backup > backup.keep:
            log_message = str(datetime.now()) + ': Removing old backups'
            backup.logfile.write(log_message)
            backup.logfile.write('\n')
            print('Removing old backups...')
            dirs.sort()

            for i in range(n_backup-backup.keep):
                try:
                    rmtree(backup.backup_dev + '/simple_backup/' + dirs[i])
                    log_message = 'Removed backup: ' + dirs[i]
                    backup.logfile.write(log_message)
                    backup.logfile.write('\n')
                except Exception:
                    err_message = 'Error while removing backup ' + dirs[i]
                    backup.errfile.write(err_message)
                    backup.errfile.write('\n')
                    print(err_message)

    backup.logfile.close()
    backup.errfile.close()
    backup.warnfile.close()

    backup.exec_()

    backup.logfile = open(backup.log_path, 'a')
    backup.errfile = open(backup.err_path, 'a')

    if islink(backup.backup_dev + '/simple_backup/last_backup'):
        try:
            os.remove(backup.backup_dev + '/simple_backup/last_backup')
        except Exception:
            err_message = 'Failed to remove last_backup link'
            backup.errfile.write(err_message)
            backup.errfile.write('\n')
            print(err_message)

    try:
        os.symlink(backup.backup_dir, backup.backup_dev + '/simple_backup/last_backup')
    except Exception:
        err_message = 'Failed to create last_backup link'
        backup.errfile.write(err_message)
        backup.errfile.write('\n')
        print(err_message)

    backup.errfile.close()

    # Update the logs
    if os.stat(backup.err_path).st_size > 0:
        log_message = str(datetime.now()) + ': Backup finished with errors (see errors.log)'
        backup.logfile.write(log_message)
        backup.logfile.write('\n')
        print('Backup finished with errors')

        try:
            move(backup.err_path, backup.homedir + '/.simple_backup/errors.log')
        except Exception:
            print('Failed to create logs in {}'.format(backup.homedir))

        try:
            os.remove(backup.warn_path)
        except Exception:
            print('Failed to remove temporary file')
    elif os.stat(backup.warn_path).st_size > 0:
        log_message = str(datetime.now()) + ': Backup finished with warnings (see warnings.log)'
        backup.logfile.write(log_message)
        backup.logfile.write('\n')
        print('Backup finished (warnings)')

        try:
            move(backup.warn_path, backup.homedir + '/.simple_backup/warnings.log')
        except Exception:
            print('Failed to create logs in {}'.format(backup.homedir))

        try:
            os.remove(backup.err_path)
        except Exception:
            print('Failed to remove temporary file')

        if isfile(backup.homedir + '/.simple_backup/errors.log'):
            try:
                os.remove(backup.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to remove old logs')
    else:
        log_message = str(datetime.now()) + ': Backup finished'
        backup.logfile.write(log_message)
        backup.logfile.write('\n')
        print('Backup finished')

        try:
            os.remove(backup.err_path)
            os.remove(backup.warn_path)
        except Exception:
            print('Failed to remove temporary files')

        if isfile(backup.homedir + '/.simple_backup/errors.log'):
            try:
                os.remove(backup.homedir + '/.simple_backup/errors.log')
            except Exception:
                print('Failed to remove old logs')
        if isfile(backup.homedir + '/.simple_backup/warnings.log'):
            try:
                os.remove(backup.homedir + '/.simple_backup/warnings.log')
            except Exception:
                print('Failed to remove old logs')

    backup.logfile.close()

    # Copy log files in home directory
    try:
        move(backup.log_path, backup.homedir + '/.simple_backup/simple_backup.log')
    except Exception:
        print('Failed to create logs in {}'.format(backup.homedir))

    # Delete temporary files
    try:
        os.remove(backup.inputs_path)
        os.remove(backup.exclude_path)
    except Exception:
        print('Failed to remove temporary files')

    exit(0)


if __name__ == '__main__':
    main()
