class AttrContainerMixin(object):
    """
    Helper class for collecting a group of named attributes. By inheriting
    this class, you get default implementation of __eq__, to_dict and __str__
    methods.
    The only requirement is you define the __slots__ attributes in your derived
    class and set it to the list of attributes.
    see :class:`tools.launcher.profilehelper.InstRef` for an example using this
    mixin.
    """
    def __eq__(self, other):
        if type(self) != type(other):
            return False

        for name in self.__slots__:
            if not getattr(self, name) == getattr(other, name):
                return False
        return True

    def to_dict(self):
        d = {name: getattr(self, name) for name in self.__slots__}
        return d

    def __str__(self):
        ret = ''
        for name in self.__slots__:
            ret += f'{name} : {getattr(self, name)}\n'
        return ret
