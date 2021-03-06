#!/usr/bin/env python

"""
Copies all the Zend tests to a temporary directory, runs them in interp mode,
then copies the good ones to test/zend/good and the bad ones to test/zend/bad.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

bad_tests = (
    # SESSION is bused on husdon
    'unset_cv05.php', 
    'unset_cv06.php',

    # unpredictable numbers - we need param matching
    'bug29971.php',
    'bug35143.php',
    'gettimeofday_basic.php',
    'localtime_basic.php',
    'time_basic.php',
    'posix_getpgid_basic.php',
    'posix_getpgid_basic.php',
    'posix_getpgrp_basic.php',
    'posix_getpid_basic.php',
    'posix_getppid_basic.php',
    'posix_getsid_basic.php',
    'posix_times_basic.php',
    'socket_getsockname.php',
    'fileinode_variation1.php',
    'filestat.php',
    'fstat_basic.php',
    'fstat.php',
    'touch_basic.php',
    'openssl_random_pseudo_bytes.php',
    'pcntl_fork_basic.php',
    'posix_times.php',
    'array_diff_assoc_variation6.php',
    'bug39322.php',
    'getmypid_basic.php',
    'getrusage_basic.php',
   
    # not implemented extensions
    'phar', # this appears in filenames

    # works in interp but not others
    'bug25922.php',
    'bug34064.php',
    'objects_029.php',
    'objects_030.php',

    # line number is inconsistent on stack overflow
    'bug41633_3.php',
)

errors = (
    # generic inconsistencies
    ('Variable passed to ([^\s]+)\(\) is not an array or object', 'Invalid operand type was used: expecting an array'),
    ('bcdiv\(\): ', ''),
    ('bcsqrt\(\): ', ''),
    ('bcpowmod\(\): ', ''),

    # I can't do math with backreferences so write them out
    ('([^\s]+)\(\) expects exactly 1 parameter, 0 given', r'Missing argument 1 for \1()'),
    ('([^\s]+)\(\) expects exactly (\d+) parameters, \d+ given', r'Missing argument \2 for \1()'),
)

parser = argparse.ArgumentParser()
parser.add_argument(
    "-z",
    "--zend_path",
    type=str,
    help="zend path to import tests from."
)
parser.add_argument(
    "-o",
    "--only",
    type=str,
    help="only import tests whose path matches this regex."
)
parser.add_argument(
    "--dirty",
    action='store_true',
    help="leave around test/zend/all directory."
)
parser.add_argument(
    "-v",
    "--verbose",
    action='store_true',
    help="print out extra stuff."
)
args = parser.parse_args()


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        pass

def walk(filename, source):
    print "Importing %s" % filename

    def split(pattern, str):
        return re.split(r'\n\s*--'+pattern+'--\s*\n', str, 1)

    def parse_headers(zend):
        sections = {}
        cur_header = None
        for line in zend.split('\n'):
            header = re.match('--([_A-Z]+)--', line)
            if header:
                cur_header = header.group(1)
                sections[cur_header] = []
            else:
                sections[cur_header].append(line)
        return sections

    sections = parse_headers(file(filename).read())
    for i in sections.keys():
        sections[i] = '\n'.join(sections[i])

    unsupported_sections = ('INI', 'POST_RAW')
    for name in unsupported_sections:
        if sections.has_key(name):
            print "Unsupported test with section --%s--: " % name, filename
            return

    if not sections.has_key('FILE'):
        print "Malformed test, no --FILE--: ", filename
        return
    
    dest_filename = os.path.basename(filename).replace('.phpt', '.php')
    source_dir = source.lower().replace('/tests', '').replace('/', '-')

    for key in ('EXPECT', 'EXPECTF', 'EXPECTREGEX'):
        if sections.has_key(key):
            exp = sections[key]
            
            # tests are really inconsistent about whitespace
            exp = re.sub(r'(\r\n|\r|\n)', '\n', exp.strip())

            exp = exp.replace('in %s on', 'in %s/%s/%s on' % ('hphp/test/zend/all', source_dir, dest_filename))

            # PHP puts a newline in that we don't
            exp = exp.replace('\n\nFatal error:', '\nFatal error:')
            exp = exp.replace('\n\nWarning:', '\nWarning:')
            exp = exp.replace('\n\nNotice:', '\nNotice:')

            match_rest_of_line = '%a'
            if key == 'EXPECTREGEX':
                match_rest_of_line = '.+'

            exp = re.sub(r'Fatal\\? error\\?:.*', 'HipHop Fatal error: '+match_rest_of_line, exp)
            exp = re.sub(r'Warning\\?:.*', 'HipHop Warning: '+match_rest_of_line, exp)
            exp = re.sub(r'Notice\\?:.*', 'HipHop Notice: '+match_rest_of_line, exp)

            for error in errors:
                exp = re.sub(error[0], error[1], exp)

            sections[key] = exp

    cur_dir = os.path.dirname(__file__)
    dest_subdir = os.path.join(cur_dir, '../test/zend/all', source_dir)
    mkdir_p(dest_subdir)
    full_dest_filename = os.path.join(dest_subdir, dest_filename)

    if sections.has_key('EXPECT'):
        exp = sections['EXPECT']
        # we use %a for error messages so always write expectf
        file(full_dest_filename+'.expectf', 'w').write(exp)
    elif sections.has_key('EXPECTREGEX'):
        exp = sections['EXPECTREGEX']
        file(full_dest_filename+'.expectregex', 'w').write(exp)
    elif sections.has_key('EXPECTF'):
        exp = sections['EXPECTF']
        file(full_dest_filename+'.expectf', 'w').write(exp)
    else:
        print "Malformed test, no --EXPECT-- or --EXPECTF-- or --EXPECTREGEX--: ", filename
        return

    test = sections['FILE']

    if sections.has_key('POST'):
        test = test.replace(
            '<?php', 
            '<?php\nparse_str("' + sections['POST'] + '", $_POST);\n'
        )
    if sections.has_key('GET'):
        test = test.replace(
            '<?php', 
            '<?php\nparse_str("' + sections['GET'] + '", $_GET);\n'
        )
    if sections.has_key('COOKIE'):
        test = test.replace(
            '<?php', 
            '<?php\n$_COOKIE = http_parse_cookie("' + sections['COOKIE'] + '");\n'
        )

    if 'bug60771.php' in full_dest_filename:
        test = test.replace("?>", "unlink('test.php');\n?>")
    if 'bug44805.php' in full_dest_filename:
        test = test.replace("1)) {\n\tunlink($file2", "2)) {\n\tunlink($file2")

    file(full_dest_filename, 'w').write(test)

if args.zend_path:
    test_dirs = (('Zend/tests'), ('tests'), ('sapi'), ('ext'))
    def should_import(filename):
        no_import = (
            # these hang forever
            '005a.php',
            'array_012.php',
            'array_pad_variation2.php',
            'bug27508.php',
            'gzgetc_basic.php',
            'gzgets_basic.php',
            'observer_003.php',
            'observer_004.php',
            'observer_005.php',
            'observer_006.php',
            'observer_009.php',
            'sleep_error.php',
            'socket_select-wrongparams-1.php',
            'test010.php',
            'usleep_error.php',

            # not implemented extensions
            '/sapi',
            '/ext/calendar',
            '/ext/com_dotnet',
            '/ext/dba',
            '/ext/dom',
            '/ext/enchant',
            '/ext/ereg',
            '/ext/fileinfo',
            '/ext/filter',
            '/ext/ftp',
            '/ext/gett/ext',
            '/ext/gmp',
            '/ext/interbase',
            '/ext/mssql',
            '/ext/mysqli',
            '/ext/mysqlnd',
            '/ext/opcache',
            '/ext/odbc',
            '/ext/pdo_dblib',
            '/ext/pdo_firebird',
            '/ext/pdo_odbc',
            '/ext/pdo_pgsql',
            '/ext/pdo_oci',
            '/ext/phar',
            '/ext/pspell',
            '/ext/readline',
            '/ext/recode',
            '/ext/reflection',
            '/ext/shmop',
            '/ext/snmp',
            '/ext/sybase_ct',
            '/ext/sysvmsg',
            '/ext/sysvsem',
            '/ext/sysvshm',
            '/ext/tidy',
            '/ext/tokenizer',
            '/ext/wddx',
            '/ext/xmlrpc',
            '/ext/xsl',
            '/ext/zip',
        )
        if not '.phpt' in filename:
            return False
        for bad in no_import:
            if bad in filename:
                return False
        return True

    for source in test_dirs:
        for root, dirs, files in os.walk(os.path.join(args.zend_path, source)):
            for filename in files:
                full_file = os.path.join(root, filename)
                if args.only and not re.search(args.only, full_file):
                    continue
                if should_import(full_file):
                    walk(full_file, root.replace(args.zend_path, ''))

if not os.path.isdir('test/zend/all'):
    if args.zend_path:
        print "No test/zend/all. Maybe no tests were imported?"
        sys.exit(0)
    else:
        print "Running all tests from test/zend/bad"
        shutil.copytree('test/zend/bad', 'test/zend/all')

print "Running all tests from zend/all"

stdout = subprocess.Popen(
    [
        'tools/verify_to_json.php',
        'run_verify.sh',
        'interp',
        'zend/all',
        '_bin',
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT
).communicate()[0]

# segfaults also print on stderr
stdout = re.sub('\nsh: line 1:.*', '', stdout)
# fbmake, you are crazy
results = json.loads('['+stdout.strip().replace("\n", ",\n")+']')[-1]['results']

if args.verbose:
    print results

for test in results:
    filename = test['name']
    good_file = filename.replace('all', 'good', 1)
    bad_file = filename.replace('all', 'bad', 1)
    mkdir_p(os.path.dirname(good_file))
    mkdir_p(os.path.dirname(bad_file))

    good = (test['status'] == 'passed')
    for test in bad_tests:
        if test in filename:
            good = False

    if good:
        dest_file = good_file
        delete_file = bad_file
        subpath = 'good'
    else:
        dest_file = bad_file
        delete_file = good_file
        subpath = 'bad'

    exps = glob.glob(filename+'.expect*')
    if not exps:
        # this file is probably generated while running tests :(
        continue

    source_file_exp = exps[0]
    _, dest_ext = os.path.splitext(source_file_exp)
    os.rename(filename, dest_file)
    file(dest_file+dest_ext, 'w').write(
        file(source_file_exp).read().replace('/all', '/' + subpath)
    )
    for f in glob.glob(delete_file+"*"):
        os.unlink(f)

if not args.dirty:
    shutil.rmtree('test/zend/all')
