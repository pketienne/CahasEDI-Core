from .templates import generic,template_operators, x12_997, x12_860, x12_856, x12_855, x12_850, x12_810
from .templates.tags import _ISA, _IEA, _GS, _GE
from . import exceptions
import io, datetime
# Class for opening and assigning correct edi template to incoming and outgoing edi files for decoding/encoding on-the-fly


# TODO: implement feature to detect Terminator/Sub-Element Separator/Repeating Carrot

terminator = b'~'
sub_separator = b'>'
repeating = b'^'


def clean_head(value : bytes):
    return value.strip(b' \t\n\r\v\f')


def discover_all_sections(start_head : bytes, end_head : bytes, bytes_list : list):
    found_list = list()
    # looping until all groups are found and added to list
    found = False
    start_i = 0
    offset = 0
    while not found:
        start_idx = None
        end_idx = None
        # TODO: Lots of integrity and error handling
        found_head = False
        for i, section in enumerate(bytes_list[start_i:]):
            if clean_head(section[0]) == start_head:
                start_idx = i + offset
                found_head = True
            elif clean_head(section[0]) == end_head and found_head:
                end_idx = i + offset
                break
        if start_idx != None and end_idx != None:
            start_i = start_idx + 1
            offset += start_i
            found_list.append(bytes_list[start_idx:end_idx + 1])
        else:
            found = True
    return found_list


class PartnershipData:

    def __init__(self, id_qualifier, my_id, partner_qualifier, partner_id):
        self._id_qualifier = id_qualifier
        self._id = my_id
        self._partner_qualifier = partner_qualifier
        self._partner_id = partner_id

    @property
    def id_qualifier(self):
        return self._id_qualifier
    @property
    def id(self):
        return self._id
    @property
    def partner_qualifier(self):
        return self._partner_qualifier
    @property
    def partner_id(self):
        return self._partner_id


class InterchangeTransaction:
    def __init__(self, partnership: PartnershipData, ctr_number = -1, usage_indicator = "T", interchg_ctr_ver_nmb="00400",interchg_stds = "U",comp_sep = '>'):
        self._partner = partnership
        self._interchg_stds = interchg_stds
        self._comp_sep = comp_sep
        self._interchg_ctr_ver_nmb = interchg_ctr_ver_nmb
        self._acknowledgment = False
        self._usage_indicator = usage_indicator
        self._auth_info_qualifier = "  "
        self._auth_info = "          "
        self._sec_info_qualifier = "  "
        self._sec_info = "          "
        self._ctr_number = ctr_number

    def _get_time_big(self):
        time = datetime.datetime.now()
        return time.strftime("%y%m%d").encode()

    def _get_time_little(self):
        time = datetime.datetime.now()
        return time.strftime("%H%M").encode()

    @property
    def acknowledge(self):
        if self._acknowledgment:
            return "1"
        else:
            return "0"
    # build ISA
    def get_bytes_list_isa(self):
        return [
            self._auth_info_qualifier.encode(),
            self._auth_info.encode(),
            self._sec_info_qualifier.encode(),
            self._sec_info.encode(),
            self._partner.id_qualifier.encode(),
            self._partner.id.encode(),
            self._partner.partner_qualifier.encode(),
            self._partner.partner_id.encode(),
            self._get_time_big(),
            self._get_time_little(),
            self._interchg_stds.encode(),
            self._interchg_ctr_ver_nmb.encode(),
            str(self._ctr_number).encode(),
            self.acknowledge.encode(),
            self._usage_indicator.encode(),
            self._comp_sep.encode()
        ]

    def get_isa(self):

        isa = _ISA()
        isa.put_bytes_list(self.get_bytes_list_isa())
        return isa

    # build IEA
    def get_bytes_list_iea(self, groups : int):
        return [
            str(groups).encode(),
            str(self._ctr_number).encode()
        ]

    def get_iea(self, groups : int):
        iea = _IEA()
        iea.put_bytes_list(self.get_bytes_list_iea(groups))
        return iea

"""
EDI Structure:

EdiHeader
    - EDI header and trailer content
    - Edi Groups (list)
        - Edi Group
            - Group header and trailer content
            - TemplateGroup (list)
                - x12_XXX.py (some template)
        - Edi Group
        
"""


class TemplateGroup(list):
    def append(self, obj:generic.Template):
        super().append(obj)


def discover_template(st_se):
    type = int(st_se[0][1])
    out = None
    for template in template_operators.template_list:
        if template.identifier_code == type:
            temp = template.get_template()
            out = temp(st_se)
    return out


class EdiGroup:
    def __init__(self,isa:_ISA ,init_data=None):
        self._GS = _GS()
        self._GE = _GE()
        self._ISA = isa

        self._template_group = TemplateGroup()
        if init_data is not None:
            self._init_group_data = init_data
            self._init_process()

    def _init_process(self):
        # Discover gs/ge
        gs = None
        ge = None

        for section in self._init_group_data:
            if clean_head(section[0]) == self._GS.tag:
                gs = section
            elif clean_head(section[0]) == self._GE.tag:
                ge = section

        if gs is not None:
            self._GS.put_bytes_list(gs[1:])
        if ge is not None:
            self._GE.put_bytes_list(ge[1:])

        # Discover all st/se
        find_list = discover_all_sections(b'ST', b'SE', self._init_group_data)
        for section in find_list:
            type = int(section[0][1])
            for template in template_operators.template_list:
                if template.identifier_code == type:
                    temp = template.get_template()
                    out = temp(section)
                    out.set_isa_gs(self._ISA, self._GS)
                    self._template_group.append(out)

    def get_content(self):
        return self._template_group


class EdiGroups(list):
    def append(self, edi_group : EdiGroup):
        super().append(edi_group)


class EdiHeader:
    def __init__(self, init_data=None):
        self._ISA = _ISA()
        self._IEA = _IEA()
        self._edi_groups = EdiGroups()

        # For transactions with single message
        self._template = None
        if init_data is not None:
            self._init_edi_file = init_data
            self._init_process()

    def _init_process(self):
        # Discover isa/iea
        isa = None
        iea = None

        for section in self._init_edi_file:
            if clean_head(section[0]) == self._ISA.tag:
                isa = section
            elif clean_head(section[0]) == self._IEA.tag:
                iea = section

        if isa is not None:
            self._ISA.put_bytes_list(isa[1:])
        if iea is not None:
            self._IEA.put_bytes_list(iea[1:])

        # discover all gs/ge Groups
        found_list = discover_all_sections(b'GS', b'GE', self._init_edi_file)

        # Check to see if no groups exist
        if found_list == []:
            found_list = discover_all_sections(b'ST', b'SE', self._init_edi_file)
            if found_list.__len__() == 1:
                self._template = discover_template(found_list[0])
            # TODO: Raise some error that either no content exists or that content is not contained in group.
            else:
                pass
        else:
            for bytes_list in found_list:
                tmp = EdiGroup(self._ISA, bytes_list)
                self._edi_groups.append(tmp)

    def append_group(self, group: EdiGroup):
        self._edi_groups.append(group)

    def append_template(self, template: generic.Template):
        self._template = template

    # Returns all content in EDI file
    def get_all_content(self):
        content = TemplateGroup()
        if self._template:
            content.append(self._template)
            return content
        for group in self._edi_groups:
            content += group.get_content()
        return content


class EdiFile:
    def __init__(self, edi_file : io.BytesIO):
        self._edi_file = edi_file
        self._separator = b'*'
        self._terminator = terminator
        self._sub_separator = sub_separator
        self._repeating = repeating
        self._assign_obj()

    def _assign_obj(self):
        self._edi_file.seek(0)
        lines = self._edi_file.readlines()

        # Check for empty files, if empty assume user is writing edi file
        if lines != []:
            self._assign_read_mod()
        else:
            self._assign_write()

    def _assign_write(self):
        pass

    def _assign_read_mod(self):
        self._edi_file.seek(0)
        lines = self._edi_file.readlines()
        out_bytes = b''

        for line in lines:
            line = line.rstrip(b'\n')
            out_bytes += line
        if out_bytes[0:3] != b'ISA':
            raise(exceptions.InvalidFileError(out_bytes[0:3]))

        self._separator = out_bytes[3:4]
        self._terminator = terminator
        self._sub_separator = sub_separator
        self._repeating = repeating

        sections = out_bytes.split(self._terminator)
        seperated_sections = list()
        for section in sections:
            seperated = section.split(self._separator)
            tmp_seperated = list()
            for sep in seperated:
                tmp_seperated.append(sep.strip())
            seperated_sections.append(tmp_seperated)
        self.edi_header = EdiHeader(seperated_sections)
