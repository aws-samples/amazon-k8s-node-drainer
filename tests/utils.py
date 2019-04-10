import collections

from types import SimpleNamespace


def dict_to_simple_namespace(orig_dict):
    def _dict_to_simple_namespace(d):
        res = {}
        for k, v in d.items():
            if isinstance(v, list):
                res[k] = [SimpleNamespace(**_dict_to_simple_namespace(x)) for x in v]
            elif isinstance(v, collections.abc.Mapping):
                res[k] = SimpleNamespace(**_dict_to_simple_namespace(v))
            else:
                res[k] = v
        return res

    return SimpleNamespace(**_dict_to_simple_namespace(orig_dict))
