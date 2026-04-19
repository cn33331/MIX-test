from collections import defaultdict
import inspect
import importlib
import pathlib
import logging
import os

from mix.driver.modulebase.mixmoduledriver import MIXModuleDriver


def search_modules(folder, root):
    mod_names = []
    for x in folder.iterdir():
        if x.name.startswith('.') or x.name.startswith('__'):
            continue

        if x.suffix not in ['.pyc', '.py', '.so']:
            if not x.is_dir():
                continue

        module_path = x.relative_to(root).with_suffix("")
        mp = module_path.as_posix().replace('/', '.')
        mod_names.append(mp)

        if x.is_dir():
            mod_names.extend(search_modules(x, root))
    return mod_names


class InstRegistry(object):

    compatible_map = {}

    @staticmethod
    def all_mix_module_classes(module):
        try:
            f = inspect.getsourcefile(module)
        except TypeError:
            logger = logging.getLogger('launcher.instreg')
            logger.debug(f'can not get source for {module}')
            return

        for name, klass in inspect.getmembers(module, inspect.isclass):
            if not issubclass(klass, MIXModuleDriver):
                continue

            # ignore classes src that is not in this file/folder
            try:
                if inspect.getsourcefile(klass) != f:
                    continue
            except Exception:
                # skip for builtin class which will cause exception at getsource
                continue
            yield klass

    @staticmethod
    def get_mix_root():
        # By default (Xavier env) we assume namespace root is '/', however in test
        # environments more commonly this assumption is not valid. MIXROOT env
        # variable allows to override to user-specific setting.
        if 'MIXROOT' in os.environ:
            return pathlib.Path(os.environ['MIXROOT'])
        else:
            return pathlib.Path('/Users/junjie/Documents/PRM/demo/PRM_SOC_MIX2_1123/')

    def __init__(self, folder_list, profile_dir='.'):
        '''
        it takes the folder list from sw_profile['module_search_paths']
        all paths can be relative, that's why we need to know the starting
        path profile_dir
        '''
        self.logger = logging.getLogger('launcher.instreg')
        folders = [pathlib.Path(profile_dir) / folder for folder in folder_list]
        self.folders = set([folder.resolve().as_posix() for folder in folders])
        self.logger.info(f"searching for mdoules in: {self.folders}")

        __map = defaultdict(list)
        module_names = []
        for folder in self.folders:
            p = pathlib.Path(folder)
            module_names.extend(search_modules(p, str(self.get_mix_root())))

        self.logger.info(f'module_names: {module_names}')

        self.modules_not_loaded = {}
        modules = []
        for m_name in module_names:
            try:
                modules.append(importlib.import_module(m_name))
            except ModuleNotFoundError as exc:
                self.logger.info(f'can not find module {m_name}: {exc}')
                self.modules_not_loaded[m_name] = str(exc)
            except Exception as e:
                self.logger.error(f'error while importing {m_name} - {e}')
                self.logger.exception(e)
                self.modules_not_loaded[m_name] = str(e)

        for mod in modules:
            for klass in self.all_mix_module_classes(mod):
                for comp_str in klass.compatible:
                    __map[comp_str].append((mod.__name__, klass.__name__))
        # change this to dict so it can be pickeled across process boundary
        self.compatible_map = dict(__map)

    def __getitem__(self, comp_str):
        try:
            return self.compatible_map[comp_str][0]
        except IndexError:
            raise RuntimeError(f"no class exist for {comp_str}")
