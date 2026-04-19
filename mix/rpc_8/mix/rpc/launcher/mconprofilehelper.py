import pathlib

from .profilehelperimpl import DefaultProfileHelper
from .mixconfig import ProfileLoader


class MCONProfileHelper(DefaultProfileHelper):

    def __init__(self, profile_dir):
        d = pathlib.Path(profile_dir).resolve()
        swp_file = d / 'sw_profile.mixconf'
        hwp_file = d / 'hw_profile.mixconf'

        creator = ProfileLoader(swp_file, hwp_file)
        super().__init__(creator.profile, profile_dir)
