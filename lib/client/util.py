# Copyright 2013-2018 Aerospike, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
import itertools
import threading
from time import time
import subprocess
import pipes


def info_to_dict(value, delimiter=';', ignore_field_without_key_value_delimiter=True):
    """
    Simple function to convert string to dict
    """
    if not value:
        return {}

    if isinstance(value, Exception):
        return value

    stat_dict = {}
    _tmp_value_list = info_to_list(value, delimiter)
    _value_list = []
    delimiter2 = "="

    if ignore_field_without_key_value_delimiter:
        _value_list = _tmp_value_list

    else:
        # Sometimes value contains confusing delimiter
        # In such cases, after splitting on delimiter, we get items without next delimiter (=).
        # By default we ignore such items. But in some cases like dc configs we need to accept those and append to previous item.
        # For ex. "dc-name=REMOTE_DC_1:nodes=2000:10:3:0:0:0:100:d+3000:int-ext-ipmap=172.68.17.123...."
        # In this example, first split will give ["dc-name=REMOTE_DC_1", "nodes=2000", "10", "3",
        # "0", "0", "100", "d+3000", "int-ext-ipmap=172.68.17.123", ....]. In such cases we need to append items
        # (10, 3, 0, 0, 100, "d+3000") to previous valid item ("nodes=2000") with delimiter (":").
        # It gives "nodes=2000:10:3:0:0:0:100:d+3000".

        for _v in _tmp_value_list:
            if delimiter2 not in _v:
                try:
                    _value_list[-1] = str(_value_list[-1]) + \
                        delimiter + str(_v)

                except Exception:
                    pass

            else:
                _value_list.append(_v)

    stat_param = itertools.imap(lambda sp: info_to_tuple(sp, delimiter2),
                                _value_list)

    for g in itertools.groupby(stat_param, lambda x: x[0]):
        try:
            value = map(lambda v: v[1], g[1])
            value = ",".join(sorted(value)) if len(value) > 1 else value[0]
            stat_dict[g[0]] = value
        except Exception:
            # NOTE: 3.0 had a bug in stats at least prior to 3.0.44. This will
            # ignore that bug.

            # Not sure if this bug is fixed or not.. removing this try/catch
            # results in things not working. TODO: investigate.
            pass
    return stat_dict


def info_to_dict_multi_level(value, keyname, delimiter1=';', delimiter2=':', ignore_field_without_key_value_delimiter=True):
    """
    Simple function to convert string to dict where string is format like
    field1_section1=value1<delimiter2>field2_section1=value2<delimiter2>... <delimiter1> field1_section2=value3<delimiter2>field2_section2=value4<delimiter2>...
    """
    if not value:
        return {}

    if isinstance(value, Exception):
        return value

    if isinstance(keyname, str):
        keyname = [keyname]

    value_list = info_to_list(value, delimiter1)
    value_dict = {}
    if not isinstance(keyname, list):
        return value_dict

    for v in value_list:
        values = info_to_dict(
            v, delimiter2, ignore_field_without_key_value_delimiter=ignore_field_without_key_value_delimiter)
        if not values or isinstance(values, Exception):
            continue
        for _k in keyname:
            if _k not in values.keys():
                continue
            value_dict[values[_k]] = values
    return value_dict


def info_colon_to_dict(value):
    """
    Simple function to convert colon separated string to dict
    """
    return info_to_dict(value, ':')


def info_to_list(value, delimiter=";"):
    if isinstance(value, Exception):
        return []
    return re.split(delimiter, value)


def info_to_tuple(value, delimiter=":"):
    return tuple(info_to_list(value, delimiter))


def find_dns(endpoints):
    if not endpoints:
        return None

    for e in endpoints:
        if not e:
            continue
        if e.startswith("[") or e[0].isdigit():
            continue
        try:
            return e.split(":")[0].strip()
        except Exception:
            pass
    return None


def parse_peers_string(s, delim=",", ignore_chars_start="[", ignore_chars_end="]"):
    o = []
    if not s or isinstance(s, Exception):
        return o
    s = s.strip()
    if not s:
        return o
    if s[0] in ignore_chars_start and s[-1] in ignore_chars_end:
        s = s[1:-1]
    if not s:
        return o
    push_bracket = ignore_chars_start
    pop_bracket = ignore_chars_end
    b_stack = []
    current_str = ""
    for i in s:
        if i == delim:
            if len(b_stack) > 0:
                current_str += i
            else:
                o.append(current_str.strip())
                current_str = ""
            continue
        if i in push_bracket:
            current_str += i
            b_stack.append(i)
            continue
        if i in pop_bracket:
            current_str += i
            b_stack.pop()
            continue
        current_str += i
    if current_str:
        o.append(current_str.strip())
    return o


def concurrent_map(func, data):
    """
    Similar to the builtin function map(). But spawn a thread for each argument
    and apply 'func' concurrently.

    Note: unlie map(), we cannot take an iterable argument. 'data' should be an
    indexable sequence.
    """

    N = len(data)
    result = [None] * N

    # Uncomment following line to run single threaded.
    # return [func(datum) for datum in data]

    # wrapper to dispose the result in the right slot
    def task_wrapper(i):
        result[i] = func(data[i])

    threads = [
        threading.Thread(target=task_wrapper, args=(i,)) for i in xrange(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return result


class cached(object):
    # Doesn't support lists, dicts and other unhashables
    # Also doesn't support kwargs for reason above.

    def __init__(self, func, ttl=0.5):
        self.func = func
        self.ttl = ttl
        self.cache = {}

    def __setitem__(self, key, value):
        self.cache[key] = (value, time() + self.ttl)

    def __getitem__(self, key):
        if key in self.cache:
            value, eol = self.cache[key]
            if eol > time():
                return value

        self[key] = self.func(*key)
        return self.cache[key][0]

    def __call__(self, *args):
        return self[args]


def flatten(list1):
    f_list = []
    for i in list1:
        if isinstance(i[0], tuple):
            for j in i:
                f_list.append(j)
        else:
            f_list.append(i)
    return f_list


def remove_suffix(input_string, suffix):
    try:
        input_string = input_string.strip()
        if not input_string.endswith(suffix):
            return input_string
        return input_string[0: input_string.rfind(suffix)]
    except Exception:
        return input_string


def get_value_from_dict(d, keys, default_value=None, return_type=None):
    if not isinstance(keys, tuple):
        keys = (keys,)
    for key in keys:
        if key in d:
            val = d[key]
            if return_type and val:
                try:
                    return return_type(val)
                except:
                    pass
            return val
    return default_value


def shell_command(command):
    """
    command is a list of ['cmd','arg1','arg2',...]
    """
    command = pipes.quote(" ".join(command))
    command = ['sh', '-c', "'%s'" % (command)]
    try:
        p = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        out, err = p.communicate()
    except Exception:
        return '', 'error'
    else:
        return out, err
