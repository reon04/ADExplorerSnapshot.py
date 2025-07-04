from adexpsnapshot.parser.structure import structure
from bloodhound.ad.utils import ADUtils
from bloodhound.enumeration.acls import LdapSid
from requests.structures import CaseInsensitiveDict

import struct
from collections import UserDict

import functools
import uuid
from io import BytesIO
import datetime, calendar

import string
from io import StringIO

ADSTYPE_INVALID = 0
ADSTYPE_DN_STRING = 1
ADSTYPE_CASE_EXACT_STRING = 2
ADSTYPE_CASE_IGNORE_STRING = 3
ADSTYPE_PRINTABLE_STRING = 4
ADSTYPE_NUMERIC_STRING = 5
ADSTYPE_BOOLEAN = 6
ADSTYPE_INTEGER = 7
ADSTYPE_OCTET_STRING = 8
ADSTYPE_UTC_TIME = 9
ADSTYPE_LARGE_INTEGER = 10
ADSTYPE_PROV_SPECIFIC = 11
ADSTYPE_OBJECT_CLASS = 12
ADSTYPE_CASEIGNORE_LIST = 13
ADSTYPE_OCTET_LIST = 14
ADSTYPE_PATH = 15
ADSTYPE_POSTALADDRESS = 16
ADSTYPE_TIMESTAMP = 17
ADSTYPE_BACKLINK = 18
ADSTYPE_TYPEDNAME = 19
ADSTYPE_HOLD = 20
ADSTYPE_NETADDRESS = 21
ADSTYPE_REPLICAPOINTER = 22
ADSTYPE_FAXNUMBER = 23
ADSTYPE_EMAIL = 24
ADSTYPE_NT_SECURITY_DESCRIPTOR = 25
ADSTYPE_UNKNOWN = 26
ADSTYPE_DN_WITH_BINARY = 27
ADSTYPE_DN_WITH_STRING = 28

class WrapStruct(object):
    def __init__(self, snap, in_obj=None):
        self.snap = snap
        self.fh = snap.fh
        self.log = snap.log

        if in_obj:
            self._data = in_obj
        else:
            self._data = getattr(structure, type(self).__name__)(self.fh)

    def __getattr__(self, attr):
        if attr.startswith('__') and attr.endswith('__'):
            raise AttributeError

        return getattr(self._data, attr)

class SystemTime(WrapStruct):
    def __init__(self, snap=None, in_obj=None):
        super().__init__(snap, in_obj)

        d = datetime.datetime(self.wYear, self.wMonth, self.wDay, self.wHour, self.wMinute, self.wSecond)
        self.unixtimestamp = calendar.timegm(d.timetuple())

    def __repr__(self):
        return str(self.unixtimestamp)

# could probably use a rewrite, but it allows us to refer to attributes dynamically,
# meaning they will be retrieved/processed when necessary 
class AttributeDict(UserDict):
    def __init__(self, obj, raw):
        self.obj = obj
        self.snap = obj.snap
        self.fh = obj.fh
        self.raw = raw

        self._dico = CaseInsensitiveDict()
        
    def __getitem__(self,  key):
        ret = self.getAttribute(key, raw=self.raw)
        if key.lower() == 'name': # hacked in to make resolve_ad_entry function work 
            return ret[0]
        return ret

    @property
    def data(self):
        if len(self._dico) > 0:
            return self._dico

        for entry in self.obj.mappingTable:
            prop = self.snap.properties[entry.attrIndex]
            self._dico[prop.propName] = self.processAttribute(prop, entry.attrOffset, self.raw)

        return self._dico

    def getAttribute(self, attrName, raw=False):
        attrIndex = self.snap.propertyDict[attrName]
        prop = self.snap.properties[attrIndex]

        for entry in self.obj.mappingTable:
            if entry.attrIndex == attrIndex:
                return self.processAttribute(prop, entry.attrOffset, raw)

        raise KeyError

    def processAttribute(self, prop, attrOffset, raw):

        attrName = prop.propName.lower()
        attrType = prop.adsType

        # at the offset at which the attribute is stored, 
        #  - the first quad indicates how many elements are in the attribute (attributes can be multi-valued), 
        #  - the bytes after depend on what sort of information is stored (e.g. for DN_STRING, the quads after are the offsets at which the element values are stored)

        fileAttrOffset = self.obj.fileOffset + attrOffset
        self.fh.seek(fileAttrOffset)
        numValues = structure.uint32(self.fh)

        values = []

        # https://docs.microsoft.com/en-us/windows/win32/api/iads/ns-iads-adsvalue
        # https://docs.microsoft.com/en-us/windows/win32/adsi/adsi-simple-data-types

        if attrType in [ADSTYPE_DN_STRING, ADSTYPE_CASE_IGNORE_STRING, ADSTYPE_CASE_IGNORE_STRING, ADSTYPE_PRINTABLE_STRING, ADSTYPE_NUMERIC_STRING, ADSTYPE_OBJECT_CLASS]:
            offsets = structure.uint32[numValues](self.fh)

            for v in range(numValues):
                self.fh.seek(fileAttrOffset + offsets[v]) # this can also be a negative offset, e.g. referencing data in a previous object
                val = structure.wchar[None](self.fh)
                values.append(val)

        elif attrType == ADSTYPE_OCTET_STRING:
            lengths = structure.uint32[numValues](self.fh)

            for v in range(numValues):
                octetStr = structure.char[lengths[v]](self.fh)
                val = octetStr

                if not raw:
                    if len(octetStr) == 16 and attrName.endswith("guid"):
                        val = str(uuid.UUID(bytes_le=octetStr))
                    elif attrName == 'objectsid':
                        val = str(LdapSid(BytesIO(octetStr)))

                values.append(val)

        elif attrType == ADSTYPE_BOOLEAN:
            assert numValues == 1, ["Multiple boolean values, verify data size", self.fileOffset, attrName]

            for v in range(numValues):
                val = bool(structure.uint32(self.fh)) # not sure if uint32 is correct type here, check against more data sets
                values.append(val)

        elif attrType == ADSTYPE_INTEGER:

            for v in range(numValues):
                # defined as DWORD, so reading as uint32 (unsigned)
                val = structure.uint32(self.fh)
                values.append(val)

        elif attrType == ADSTYPE_LARGE_INTEGER:

            for v in range(numValues):
                # defined as LARGE_INTEGER, interestingly this is an int64 (signed) according to MS docs
                val = structure.int64(self.fh)
                values.append(val)

        elif attrType == ADSTYPE_UTC_TIME: # note that date/times can also be returned as Interval type instead (ADSTYPE_LARGE_INTEGER) - actual time units depend on which attribute is using it

            for v in range(numValues):
                systime = SystemTime(self.snap)
                val = systime.unixtimestamp
                values.append(val)

        elif attrType == ADSTYPE_NT_SECURITY_DESCRIPTOR:

            for v in range(numValues):
                lenDescriptorBytes = structure.uint32(self.fh)
                descriptorBytes = self.fh.read(lenDescriptorBytes)
                values.append(descriptorBytes)

        else:
            if self.snap.log:
                self.snap.log.warn("Unhandled adsType: %s -> %d" % (attrName, attrType))

        return values

class Object(WrapStruct):
    def __init__(self, snap=None, in_obj=None):
        super().__init__(snap, in_obj)

        self.fileOffset = self.fh.tell() - 4 - 4 - (self.tableSize * 8)
        self.fh.seek(self.fileOffset + self.objSize) # move file pointer to the next object

        self.attributes = AttributeDict(self, raw=False)
        self.raw_attributes = AttributeDict(self, raw=True)

    @functools.cached_property
    def classes(self):
        try:
            return list(map(str.casefold, self.attributes.get('objectClass', [])))
        except Exception as e:
            print("Error in resolving objectClass:")
            print(e)
        return []

    @functools.cached_property
    def category(self):
        catDN = self.attributes.get('objectCategory', None)
        if catDN is None:
            return None

        catDN = catDN[0]
        catObj = self.snap.classes.get(catDN, None)
        if catObj:
            return catObj.className.lower()
        else:
            return None

    # for easy compatibility with the bloodhound lib
    def __getitem__(self, key):
        if key == "attributes":
            return self.attributes
        elif key == "raw_attributes":
            return self.raw_attributes
        else:
            return None

class Property(WrapStruct):
    def __init__(self, snap=None, in_obj=None):
        super().__init__(snap, in_obj)

        self.propName = self.propName.rstrip('\x00')
        self.DN = self.DN.rstrip('\x00')
        self.schemaIDGUID = uuid.UUID(bytes_le=self.schemaIDGUID)

class Class(WrapStruct):
    def __init__(self, snap=None, in_obj=None):
        super().__init__(snap, in_obj)

        self.className = self.className.rstrip('\x00')
        self.DN = self.DN.rstrip('\x00')
        self.schemaIDGUID = uuid.UUID(bytes_le=self.schemaIDGUID)

class Header(WrapStruct):
    def __init__(self, snap, in_obj=None):
        super().__init__(snap, in_obj)

        self.server = self.server.rstrip('\x00')
        self.mappingOffset = (self.fileoffsetHigh << 32) | self.fileoffsetLow
        self.filetimeUnix = ADUtils.win_timestamp_to_unix(self.filetime)

class Snapshot(object):
    def __init__(self, fh, log=None):
        self.fh = fh
        self.log = log
        self.objectOffsets = {}

        # the order in which we're parsing matters, due to the file handle's position
        # typically, you would call as follows:

        # self.parseHeader()
        # self.parseObjectOffsets()
        # self.parseProperties()
        # self.parseClasses()
        # self.parseRights()

    def parseHeader(self):
        self.fh.seek(0)
        self.header = Header(self)

    def parseObjectOffsets(self):
        self.fh.seek(0x43e)

        # we are only keeping offsets at this stage, as some databases grow very big

        if self.log:
            prog = self.log.progress(f"Parsing object offsets", rate=0.1)

        self.objectOffsets = []
        for i in range(self.header.numObjects):
            pos = self.fh.tell()
            objSize = struct.unpack("<I", self.fh.read(4))[0]

            self.objectOffsets.append(pos) 
            # using struct instead of dissect.cstruct here for speed
            #self.objectOffsets.append(Object(self).fileOffset)
            self.fh.seek(pos+objSize)

            if self.log and self.log.term_mode:
                prog.status(f"{i+1}/{self.header.numObjects}")

        if self.log:
            prog.success(f"{len(self.objectOffsets)}")

    def getObject(self, i):
        self.fh.seek(self.objectOffsets[i])
        return Object(self)

    def getObjects(self):
        i = 0
        while i < self.header.numObjects:
            yield self.getObject(i)
            i += 1

    objects = property(getObjects)

    def parseProperties(self):
        if self.log:
            prog = self.log.progress("Parsing properties")

        self.fh.seek(self.header.mappingOffset)

        properties_with_header = structure.Properties(self.fh)
        self.properties = []
        self.propertyDict = CaseInsensitiveDict()

        for idx, p in enumerate(properties_with_header.properties):
            prop = Property(self, in_obj=p)
            self.properties.append(prop)

            # abuse our dict for both DNs and the display name / cn
            self.propertyDict[prop.propName] = idx
            self.propertyDict[prop.DN] = idx
            self.propertyDict[prop.DN.split(',')[0].split('=')[1]] = idx

        if self.log:
            prog.success(str(properties_with_header.numProperties))

    def parseClasses(self):
        if self.log:
            prog = self.log.progress("Parsing classes")

        classes_with_header = structure.Classes(self.fh)
        self.classes = CaseInsensitiveDict()
        for c in classes_with_header.classes:
            cl = Class(self, in_obj=c)

            # abuse our dict for both DNs and the display name / cn
            self.classes[cl.className] = cl
            self.classes[cl.DN] = cl
            self.classes[cl.DN.split(',')[0].split('=')[1]] = cl

        if self.log:
            prog.success(str(classes_with_header.numClasses))

    def parseRights(self):
        if self.log:
            prog = self.log.progress("Parsing rights")

        rights_with_header = structure.Rights(self.fh)
        self.rights = rights_with_header.rights

        if self.log:
            prog.success(str(rights_with_header.numRights))

class CaseInsensitiveDefaultDict(CaseInsensitiveDict):
    def __init__(self, *args, **kwargs):
        if 'default_factory' in kwargs:
            self.default = kwargs['default_factory']
            del kwargs['default_factory']
        elif len(args) > 0:
            self.default = args[0]
            args = args[1:]
        else:
            self.default = None
        CaseInsensitiveDict.__init__(self, *args, **kwargs)

    def __repr__(self):
        return 'CaseInsensitiveDefaultDict(%s, %s)' % (self.default, CaseInsensitiveDict.__repr__(self))

    def __missing__(self, key):
        if self.default:
            value = self.default()
            CaseInsensitiveDict.__setitem__(self, key, value)
            return value
        else:
            raise KeyError(key)

    def __getitem__(self, key):
        try:
            return CaseInsensitiveDict.__getitem__(self, key)
        except KeyError:
            return self.__missing__(key)

# modified version of https://gist.github.com/markscottwright/329d1638b1c3b10a54ffd413f6a89b93
# used for parsing distinguished names into its components
class DN:
    class _Peekable:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.last_char = None

        def next_char(self):
            if self.last_char is not None:
                t = self.last_char
                self.last_char = None
                return t
            else:
                return self.wrapped.read(1)

        def push(self, c):
            self.last_char = c

    def _read_attribute(dn_reader):
        """read up to and consume ="""
        attribute = ''
        while (c := dn_reader.next_char()) != '=':
            if c == '':
                raise Exception("DN parsing error")
            attribute += c
        return attribute

    def _read_string(dn_reader):
        s = ""
        spaces = ''
        # skip leading whitespace
        while (c := dn_reader.next_char()) != '':
            if c == ',' or c == '+':
                dn_reader.push(c)
                break
            elif c == ' ':
                spaces += c
            else:
                # only add spaces we've seen if we're in the middle of a string
                if s != '':
                    s += spaces

                spaces = ''
                if c == '\\':
                    next_c = dn_reader.next_char()
                    if next_c in r'"+,;\<>=':
                        s += next_c
                    elif next_c in "0123456789abcdefABCDEF":
                        hexchar2 = dn_reader.next_char()
                        s += chr(int(next_c + hexchar2, 16))
                else:
                    s += c

        return s

    def _read_rdn(dn_reader, normalize_attributes):
        out = [DN._read_name_and_attribute(dn_reader, normalize_attributes)]
        while (c := dn_reader.next_char()) == '+':
            out.append(DN._read_name_and_attribute(dn_reader, normalize_attributes))
        dn_reader.push(c)
        return out

    def _read_name_and_attribute(dn_reader, normalize_attributes):
        if normalize_attributes:
            return DN._read_attribute(dn_reader).upper() + "=" + DN._read_string(dn_reader)
        else:
            return DN._read_attribute(dn_reader) + "=" + DN._read_string(dn_reader)

    def _read_dn(dn_reader, normalize_attributes):
        out = [DN._read_rdn(dn_reader, normalize_attributes)]
        while (c := dn_reader.next_char()) == ',':
            out.append(DN._read_rdn(dn_reader, normalize_attributes))
        dn_reader.push(c)
        return out

    def parse_dn(s: str, normalize_attributes=True) -> list[list[str]]:
        r"""
        Given a DN string, return a list of rdns, where an rdn is a list of "attribute=value"
        >>> parse_dn(r'CN=Mark Wright,OU=Spectre+UID=1234,C=US')
        [['CN=Mark Wright'], ['OU=Spectre', 'UID=1234'], ['C=US']]
        >>> parse_dn(r'CN=    Mark Wright\20   ')
        [['CN=Mark Wright ']]
        """
        return DN._read_dn(DN._Peekable(StringIO(s)), normalize_attributes)

    def _name_and_attribute_to_string(n):
        value_position = n.index('=') + 1

        last_non_space_position = len(n)-1
        while n[last_non_space_position] == ' ':
            last_non_space_position -= 1

        out = n[0:value_position]
        char_seen = False
        for p in range(value_position, last_non_space_position+1):
            if n[p] == ' ' and not char_seen:
                out += r"\20";
            else:
                char_seen = True
                if n[p] in r'"+,;\<>=':
                    out += "\\" + n[p]
                elif n[p] in string.printable:
                    out += n[p]
                else:
                    out += "\\02x" % ord(n[p])

        out += "\\20" * (len(n) - last_non_space_position - 1)
        return out

    def _rdn_to_string(rdn):
        return "+".join(DN._name_and_attribute_to_string(n) for n in rdn)

    def dn_to_string(dn: list[list[str]]) -> str:
        out = ''
        return ",".join(DN._rdn_to_string(rdn) for rdn in dn)
