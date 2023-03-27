# -*- coding: utf-8 -*-

from collections import namedtuple
from dataclasses import dataclass, field
from enum import Enum
from itertools import zip_longest
from typing import Any, Dict, List, Optional, Tuple, Union

from wireviz.wv_bom import (
    BomHash,
    BomHashList,
    PartNumberInfo,
    QtyMultiplierCable,
    QtyMultiplierConnector,
)
from wireviz.wv_colors import (
    COLOR_CODES,
    ColorOutputMode,
    MultiColor,
    SingleColor,
    get_color_by_colorcode_index,
)
from wireviz.wv_utils import aspect_ratio, awg_equiv, mm2_equiv, remove_links

# Each type alias have their legal values described in comments
# - validation might be implemented in the future
PlainText = str  # Text not containing HTML tags nor newlines
Hypertext = str  # Text possibly including HTML hyperlinks that are removed in all outputs except HTML output
MultilineHypertext = (
    str  # Hypertext possibly also including newlines to break lines in diagram output
)

Designator = PlainText  # Case insensitive unique name of connector or cable

# Literal type aliases below are commented to avoid requiring python 3.8
ImageScale = PlainText  # = Literal['false', 'true', 'width', 'height', 'both']

# Type combinations
Pin = Union[int, PlainText]  # Pin identifier
PinIndex = int  # Zero-based pin index
Wire = Union[int, PlainText]  # Wire number or Literal['s'] for shield
NoneOrMorePins = Union[
    Pin, Tuple[Pin, ...], None
]  # None, one, or a tuple of pin identifiers
NoneOrMorePinIndices = Union[
    PinIndex, Tuple[PinIndex, ...], None
]  # None, one, or a tuple of zero-based pin indices
OneOrMoreWires = Union[Wire, Tuple[Wire, ...]]  # One or a tuple of wires

# Metadata can contain whatever is needed by the HTML generation/template.
MetadataKeys = PlainText  # Literal['title', 'description', 'notes', ...]


Side = Enum("Side", "LEFT RIGHT")
ArrowDirection = Enum("ArrowDirection", "NONE BACK FORWARD BOTH")
ArrowWeight = Enum("ArrowWeight", "SINGLE DOUBLE")
NumberAndUnit = namedtuple("NumberAndUnit", "number unit")

AUTOGENERATED_PREFIX = "AUTOGENERATED_"


@dataclass
class Arrow:
    direction: ArrowDirection
    weight: ArrowWeight


class Metadata(dict):
    pass


@dataclass
class Options:
    fontname: PlainText = "arial"
    bgcolor: SingleColor = "WH"  # will be converted to SingleColor in __post_init__
    bgcolor_node: SingleColor = "WH"
    bgcolor_connector: SingleColor = None
    bgcolor_cable: SingleColor = None
    bgcolor_bundle: SingleColor = None
    color_output_mode: ColorOutputMode = ColorOutputMode.EN_UPPER
    mini_bom_mode: bool = True
    template_separator: str = "."
    _pad: int = 0
    # TODO: resolve template and image paths during rendering, not during YAML parsing
    _template_paths: List = field(default_factory=list)
    _image_paths: List = field(default_factory=list)

    def __post_init__(self):

        self.bgcolor = SingleColor(self.bgcolor)
        self.bgcolor_node = SingleColor(self.bgcolor_node)
        self.bgcolor_connector = SingleColor(self.bgcolor_connector)
        self.bgcolor_cable = SingleColor(self.bgcolor_cable)
        self.bgcolor_bundle = SingleColor(self.bgcolor_bundle)

        if not self.bgcolor_node:
            self.bgcolor_node = self.bgcolor
        if not self.bgcolor_connector:
            self.bgcolor_connector = self.bgcolor_node
        if not self.bgcolor_cable:
            self.bgcolor_cable = self.bgcolor_node
        if not self.bgcolor_bundle:
            self.bgcolor_bundle = self.bgcolor_cable


@dataclass
class Tweak:
    override: Optional[Dict[Designator, Dict[str, Optional[str]]]] = None
    append: Union[str, List[str], None] = None


@dataclass
class Image:
    # Attributes of the image object <img>:
    src: str
    scale: Optional[ImageScale] = None
    # Attributes of the image cell <td> containing the image:
    width: Optional[int] = None
    height: Optional[int] = None
    fixedsize: Optional[bool] = None
    bgcolor: SingleColor = None
    # Contents of the text cell <td> just below the image cell:
    caption: Optional[MultilineHypertext] = None
    # See also HTML doc at https://graphviz.org/doc/info/shapes.html#html

    def __post_init__(self):

        self.bgcolor = SingleColor(self.bgcolor)

        if self.fixedsize is None:
            # Default True if any dimension specified unless self.scale also is specified.
            self.fixedsize = (self.width or self.height) and self.scale is None

        if self.scale is None:
            if not self.width and not self.height:
                self.scale = "false"
            elif self.width and self.height:
                self.scale = "both"
            else:
                self.scale = "true"  # When only one dimension is specified.

        if self.fixedsize:
            # If only one dimension is specified, compute the other
            # because Graphviz requires both when fixedsize=True.
            if self.height:
                if not self.width:
                    self.width = self.height * aspect_ratio(self.src)
            else:
                if self.width:
                    self.height = self.width / aspect_ratio(self.src)


@dataclass
class PinClass:
    index: int
    id: str
    label: str
    color: MultiColor
    parent: str  # designator of parent connector
    _num_connections = 0  # incremented in Connector.connect()
    _anonymous: bool = False  # true for pins on autogenerated connectors
    _simple: bool = False  # true for simple connector

    def __str__(self):
        snippets = [  # use str() for each in case they are int or other non-str
            str(self.parent) if not self._anonymous else "",
            str(self.id) if not self._anonymous and not self._simple else "",
            str(self.label) if self.label else "",
        ]
        return ":".join([snip for snip in snippets if snip != ""])


@dataclass
class Component:
    category: Optional[str] = None  # currently only used by cables, to define bundles
    type: Union[MultilineHypertext, List[MultilineHypertext]] = None
    subtype: Union[MultilineHypertext, List[MultilineHypertext]] = None

    # part number
    partnumbers: PartNumberInfo = None  # filled by fill_partnumbers()
    # the following are provided for user convenience and should not be accessed later.
    # their contents are loaded into partnumbers during the child class __post_init__()
    pn: str = None
    manufacturer: str = None
    mpn: str = None
    supplier: str = None
    spn: str = None
    # BOM info
    qty: NumberAndUnit = NumberAndUnit(1, None)
    amount: Optional[NumberAndUnit] = None
    sum_amounts_in_bom: bool = True
    ignore_in_bom: bool = False
    bom_id: Optional[str] = None  # to be filled after harness is built

    def fill_partnumbers(self):
        partnos = [self.pn, self.manufacturer, self.mpn, self.supplier, self.spn]
        partnos = [remove_links(entry) for entry in partnos]
        partnos = tuple(partnos)
        self.partnumbers = PartNumberInfo(*partnos)

    def parse_number_and_unit(
        self,
        inp: Optional[Union[NumberAndUnit, float, int, str]],
        default_unit: Optional[str] = None,
    ) -> Optional[NumberAndUnit]:
        if inp is None:
            return None
        elif isinstance(inp, NumberAndUnit):
            return inp
        elif isinstance(inp, float) or isinstance(inp, int):
            return NumberAndUnit(float(inp), default_unit)
        elif isinstance(inp, str):
            if " " in inp:
                number, unit = inp.split(" ", 1)
            else:
                number, unit = inp, default_unit
            try:
                number = float(number)
            except ValueError:
                raise Exception(
                    f"{inp} is not a valid number and unit.\n"
                    "It must be a number, or a number and unit separated by a space."
                )
            else:
                return NumberAndUnit(number, unit)

    @property
    def bom_hash(self) -> BomHash:
        if self.sum_amounts_in_bom:
            _hash = BomHash(
                description=self.description,
                qty_unit=self.amount.unit if self.amount else None,
                amount=None,
                partnumbers=self.partnumbers,
            )
        else:
            _hash = BomHash(
                description=self.description,
                qty_unit=self.qty.unit,
                amount=self.amount,
                partnumbers=self.partnumbers,
            )
        return _hash

    @property
    def bom_qty(self) -> float:
        if self.sum_amounts_in_bom:
            if self.amount:
                return self.qty.number * self.amount.number
            else:
                return self.qty.number
        else:
            return self.qty.number

    def bom_amount(self) -> NumberAndUnit:
        if self.sum_amounts_in_bom:
            return NumberAndUnit(None, None)
        else:
            return self.amount

    @property    
    def has_pn_info(self) -> bool:
        return any([self.pn, self.manufacturer, self.mpn, self.supplier, self.spn])


@dataclass
class AdditionalComponent(Component):
    qty_multiplier: Union[QtyMultiplierConnector, QtyMultiplierCable, int] = 1
    _qty_multiplier_computed: Union[int, float] = 1
    designators: Optional[str] = None  # used for components definedi in the
    #                                    additional_bom_items section within another component
    bgcolor: SingleColor = None  #       ^ same here
    note: str = None

    def __post_init__(self):
        super().fill_partnumbers()
        self.bgcolor = SingleColor(self.bgcolor)
        self.qty = self.parse_number_and_unit(self.qty, None)
        self.amount = self.parse_number_and_unit(self.amount, None)

        if isinstance(self.qty_multiplier, float) or isinstance(
            self.qty_multiplier, int
        ):
            pass
        else:
            self.qty_multiplier = self.qty_multiplier.upper()
            if self.qty_multiplier in QtyMultiplierConnector.__members__.keys():
                self.qty_multiplier = QtyMultiplierConnector[self.qty_multiplier]
            elif self.qty_multiplier in QtyMultiplierCable.__members__.keys():
                self.qty_multiplier = QtyMultiplierCable[self.qty_multiplier]
            else:
                raise Exception(f"Unknown qty multiplier: {self.qty_multiplier}")

    @property
    def additional_components(self):
        # an additional component may not have further nested additional comonents
        return []

    @property
    def bom_qty(self):
        return self.qty.number * self._qty_multiplier_computed

    @property
    def description(self) -> str:
        return f"{self.type}{', ' + self.subtype if self.subtype else ''}"


@dataclass
class GraphicalComponent(Component):  # abstract class, for future use
    bgcolor: Optional[SingleColor] = None


@dataclass
class TopLevelGraphicalComponent(GraphicalComponent):  # abstract class
    # component properties
    designator: Designator = None
    color: Optional[MultiColor] = None
    image: Optional[Image] = None
    additional_parameters: Optional[Dict] = None
    additional_components: List[AdditionalComponent] = field(default_factory=list)
    notes: Optional[MultilineHypertext] = None
    # BOM options
    add_up_in_bom: Optional[bool] = None
    # rendering options
    bgcolor_title: Optional[SingleColor] = None
    show_name: Optional[bool] = None


@dataclass
class Connector(TopLevelGraphicalComponent):
    # connector-specific properties
    style: Optional[str] = None
    category: Optional[str] = None
    loops: List[List[Pin]] = field(default_factory=list)
    # pin information in particular
    pincount: Optional[int] = None
    pins: List[Pin] = field(default_factory=list)  # legacy
    pinlabels: List[Pin] = field(default_factory=list)  # legacy
    pincolors: List[str] = field(default_factory=list)  # legacy
    pin_objects: Dict[Any, PinClass] = field(default_factory=dict)  # new
    # rendering option
    show_pincount: Optional[bool] = None
    hide_disconnected_pins: bool = False

    @property
    def is_autogenerated(self):
        return self.designator.startswith(AUTOGENERATED_PREFIX)

    @property
    def description(self) -> str:
        substrs = [
            "Connector",
            self.type,
            self.subtype,
            f"{self.pincount} pins" if self.show_pincount else None,
            str(self.color) if self.color else None,
        ]
        return ", ".join([str(s) for s in substrs if s is not None and s != ""])

    def should_show_pin(self, pin_id):
        return (
            not self.hide_disconnected_pins
            or self.pin_objects[pin_id]._num_connections > 0
        )

    @property
    def unit(self):  # for compatibility with BOM hashing
        return None  # connectors do not support units.

    def __post_init__(self) -> None:

        super().fill_partnumbers()

        self.bgcolor = SingleColor(self.bgcolor)
        self.bgcolor_title = SingleColor(self.bgcolor_title)
        self.color = MultiColor(self.color)

        # connectors do not support custom qty or amount
        self.qty = NumberAndUnit(1, None)
        self.amount = None

        if isinstance(self.image, dict):
            self.image = Image(**self.image)

        self.ports_left = False
        self.ports_right = False
        self.visible_pins = {}

        if self.style == "simple":
            if self.pincount and self.pincount > 1:
                raise Exception(
                    "Connectors with style set to simple may only have one pin"
                )
            self.pincount = 1

        if not self.pincount:
            self.pincount = max(
                len(self.pins), len(self.pinlabels), len(self.pincolors)
            )
            if not self.pincount:
                raise Exception(
                    "You need to specify at least one: "
                    "pincount, pins, pinlabels, or pincolors"
                )

        # create default list for pins (sequential) if not specified
        if not self.pins:
            self.pins = list(range(1, self.pincount + 1))

        if len(self.pins) != len(set(self.pins)):
            raise Exception("Pins are not unique")

        # all checks have passed
        pin_tuples = zip_longest(
            self.pins,
            self.pinlabels,
            self.pincolors,
        )
        for pin_index, (pin_id, pin_label, pin_color) in enumerate(pin_tuples):
            self.pin_objects[pin_id] = PinClass(
                index=pin_index,
                id=pin_id,
                label=pin_label,
                color=MultiColor(pin_color),
                parent=self.designator,
                _anonymous=self.is_autogenerated,
                _simple=self.style == "simple",
            )

        if self.show_name is None:
            self.show_name = self.style != "simple" and not self.is_autogenerated

        if self.show_pincount is None:
            # hide pincount for simple (1 pin) connectors by default
            self.show_pincount = self.style != "simple"

        for loop in self.loops:
            # TODO: check that pins to connect actually exist
            # TODO: allow using pin labels in addition to pin numbers,
            #       just like when defining regular connections
            # TODO: include properties of wire used to create the loop
            if len(loop) != 2:
                raise Exception("Loops must be between exactly two pins!")
            # side=None, determine side to show loops during rendering
            self.activate_pin(loop[0], side=None, is_connection=True)
            self.activate_pin(loop[1], side=None, is_connection=True)

        for i, item in enumerate(self.additional_components):
            if isinstance(item, dict):
                self.additional_components[i] = AdditionalComponent(**item)

    def activate_pin(self, pin_id, side: Side = None, is_connection=True) -> None:
        if is_connection:
            self.pin_objects[pin_id]._num_connections += 1
        if side == Side.LEFT:
            self.ports_left = True
        elif side == Side.RIGHT:
            self.ports_right = True

    def compute_qty_multipliers(self):
        # do not run before all connections in harness have been made!
        num_populated_pins = len(
            [pin for pin in self.pin_objects.values() if pin._num_connections > 0]
        )
        num_connections = sum(
            [pin._num_connections for pin in self.pin_objects.values()]
        )
        qty_multipliers_computed = {
            "PINCOUNT": self.pincount,
            "POPULATED": num_populated_pins,
            "CONNECTIONS": num_connections,
        }
        for subitem in self.additional_components:
            if isinstance(subitem.qty_multiplier, QtyMultiplierConnector):
                computed_factor = qty_multipliers_computed[subitem.qty_multiplier.name]
            elif isinstance(subitem.qty_multiplier, QtyMultiplierCable):
                raise Exception("Used a cable multiplier in a connector!")
            else:  # int or float
                computed_factor = subitem.qty_multiplier
            subitem._qty_multiplier_computed = computed_factor


@dataclass
class WireClass:
    parent: str  # designator of parent cable/bundle
    # wire-specific properties
    index: int
    id: str
    label: str
    color: MultiColor
    # ...
    bom_id: Optional[str] = None  # to be filled after harness is built
    # inheritable from parent cable
    type: Union[MultilineHypertext, List[MultilineHypertext]] = None
    subtype: Union[MultilineHypertext, List[MultilineHypertext]] = None
    gauge: Optional[NumberAndUnit] = None
    length: Optional[NumberAndUnit] = None
    ignore_in_bom: Optional[bool] = False
    sum_amounts_in_bom: bool = True
    partnumbers: PartNumberInfo = None

    @property
    def bom_hash(self) -> BomHash:
        if self.sum_amounts_in_bom:
            _hash = BomHash(
                description=self.description,
                qty_unit=self.length.unit if self.length else None,
                amount=None,
                partnumbers=self.partnumbers,
            )
        else:
            _hash = BomHash(
                description=self.description,
                qty_unit=None,
                amount=self.length,
                partnumbers=self.partnumbers,
            )
        return _hash

    @property
    def gauge_str(self):
        if not self.gauge:
            return None
        actual_gauge = f"{self.gauge.number} {self.gauge.unit}"
        actual_gauge = actual_gauge.replace("mm2", "mm\u00B2")
        return actual_gauge

    @property
    def description(self) -> str:
        substrs = [
            "Wire",
            self.type,
            self.subtype,
            self.gauge_str,
            str(self.color) if self.color else None,
        ]
        desc = ", ".join([s for s in substrs if s is not None and s != ""])
        return desc


@dataclass
class ShieldClass(WireClass):
    pass  # TODO, for wires with multiple shields more shield details, ...


@dataclass
class Connection:
    from_: PinClass = None
    via: Union[WireClass, ShieldClass] = None
    to: PinClass = None


@dataclass
class Cable(TopLevelGraphicalComponent):
    # cable-specific properties
    gauge: Optional[NumberAndUnit] = None
    length: Optional[NumberAndUnit] = None
    color_code: Optional[str] = None
    # wire information in particular
    wirecount: Optional[int] = None
    shield: Union[bool, MultiColor] = False
    colors: List[str] = field(default_factory=list)  # legacy
    wirelabels: List[Wire] = field(default_factory=list)  # legacy
    wire_objects: Dict[Any, WireClass] = field(default_factory=dict)  # new
    # internal
    _connections: List[Connection] = field(default_factory=list)
    # rendering options
    show_name: Optional[bool] = None
    show_equiv: bool = False
    show_wirecount: bool = True
    show_wirenumbers: Optional[bool] = None

    @property
    def is_autogenerated(self):
        return self.designator.startswith(AUTOGENERATED_PREFIX)

    @property
    def unit(self):  # for compatibility with parent class
        return self.length

    @property
    def gauge_str(self):
        if not self.gauge:
            return None
        actual_gauge = f"{self.gauge.number} {self.gauge.unit}"
        actual_gauge = actual_gauge.replace("mm2", "mm\u00B2")
        return actual_gauge

    @property
    def gauge_str_with_equiv(self):
        if not self.gauge:
            return None
        actual_gauge = self.gauge_str
        equivalent_gauge = ""
        if self.show_equiv:
            # convert unit if known
            if self.gauge.unit == "mm2":
                equivalent_gauge = f" ({awg_equiv(self.gauge.number)} AWG)"
            elif self.gauge.unit.upper() == "AWG":
                equivalent_gauge = f" ({mm2_equiv(self.gauge.number)} mm2)"
        out = f"{actual_gauge}{equivalent_gauge}"
        out = out.replace("mm2", "mm\u00B2")
        return out

    @property
    def length_str(self):
        if not self.length:
            return None
        out = f"{self.length.number} {self.length.unit}"
        return out

    @property
    def bom_hash(self):
        if self.category == "bundle":
            raise Exception("Do this at the wire level!")  # TODO
        else:
            return super().bom_hash

    @property
    def description(self) -> str:
        if self.category == "bundle":
            raise Exception("Do this at the wire level!")  # TODO
        else:
            substrs = [
                ("", "Cable"),
                (", ", self.type),
                (", ", self.subtype),
                (", ", self.wirecount),
                (" ", f"x {self.gauge_str}" if self.gauge else "wires"),
                (" ", "shielded" if self.shield else None),
                (", ", str(self.color) if self.color else None),
            ]
            desc = "".join(
                [f"{s[0]}{s[1]}" for s in substrs if s[1] is not None and s[1] != ""]
            )
            return desc

    def _get_wire_partnumber(self, idx) -> PartNumberInfo:
        def _get_correct_element(inp, idx):
            return inp[idx] if isinstance(inp, List) else inp

        # TODO: possibly make more robust/elegant
        if self.category == "bundle":
            return PartNumberInfo(
                _get_correct_element(self.partnumbers.pn, idx),
                _get_correct_element(self.partnumbers.manufacturer, idx),
                _get_correct_element(self.partnumbers.mpn, idx),
                _get_correct_element(self.partnumbers.supplier, idx),
                _get_correct_element(self.partnumbers.spn, idx),
            )
        else:
            return None  # non-bundles do not support lists of part data

    def __post_init__(self) -> None:

        super().fill_partnumbers()

        self.bgcolor = SingleColor(self.bgcolor)
        self.bgcolor_title = SingleColor(self.bgcolor_title)
        self.color = MultiColor(self.color)

        if isinstance(self.image, dict):
            self.image = Image(**self.image)

        # TODO:
        # allow gauge, length, and other fields to be lists too (like part numbers),
        # and assign them the same way to bundles.

        self.gauge = self.parse_number_and_unit(self.gauge, "mm2")
        self.length = self.parse_number_and_unit(self.length, "m")
        self.amount = self.length  # for BOM

        if self.wirecount:  # number of wires explicitly defined
            if self.colors:  # use custom color palette (partly or looped if needed)
                self.colors = [
                    self.colors[i % len(self.colors)] for i in range(self.wirecount)
                ]
            elif self.color_code:
                # use standard color palette (partly or looped if needed)
                if self.color_code not in COLOR_CODES:
                    raise Exception("Unknown color code")
                self.colors = [
                    get_color_by_colorcode_index(self.color_code, i)
                    for i in range(self.wirecount)
                ]
            else:  # no colors defined, add dummy colors
                self.colors = [""] * self.wirecount

        else:  # wirecount implicit in length of color list
            if not self.colors:
                raise Exception(
                    "Unknown number of wires. "
                    "Must specify wirecount or colors (implicit length)"
                )
            self.wirecount = len(self.colors)

        if self.wirelabels:
            if self.shield and "s" in self.wirelabels:
                raise Exception(
                    '"s" may not be used as a wire label for a shielded cable.'
                )

        # if lists of part numbers are provided,
        # check this is a bundle and that it matches the wirecount.
        for idfield in [self.manufacturer, self.mpn, self.supplier, self.spn, self.pn]:
            if isinstance(idfield, list):
                if self.category == "bundle":
                    # check the length
                    if len(idfield) != self.wirecount:
                        raise Exception("lists of part data must match wirecount")
                else:
                    raise Exception("lists of part data are only supported for bundles")

        # all checks have passed
        wire_tuples = zip_longest(
            # TODO: self.wire_ids
            self.colors,
            self.wirelabels,
        )
        for wire_index, (wire_color, wire_label) in enumerate(wire_tuples):
            id = wire_index + 1
            self.wire_objects[id] = WireClass(
                parent=self.designator,
                # wire-specific properties
                index=wire_index,  # TODO: wire_id
                id=id,  # TODO: wire_id
                label=wire_label,
                color=MultiColor(wire_color),
                # inheritable from parent cable
                type=self.type,
                subtype=self.subtype,
                gauge=self.gauge,
                length=self.length,
                sum_amounts_in_bom=self.sum_amounts_in_bom,
                ignore_in_bom=self.ignore_in_bom,
                partnumbers=self._get_wire_partnumber(wire_index),
            )

        if self.shield:
            index_offset = len(self.wire_objects)
            # TODO: add support for multiple shields
            id = "s"
            self.wire_objects[id] = ShieldClass(
                index=index_offset,
                id=id,
                label="Shield",
                color=MultiColor(self.shield)
                if isinstance(self.shield, str)
                else MultiColor(None),
                parent=self.designator,
            )

        if self.show_name is None:
            self.show_name = not self.is_autogenerated

        if self.show_wirenumbers is None:
            # by default, show wire numbers for cables, hide for bundles
            self.show_wirenumbers = self.category != "bundle"

        for i, item in enumerate(self.additional_components):
            if isinstance(item, dict):
                self.additional_components[i] = AdditionalComponent(**item)

    def _connect(
        self,
        from_pin_obj: List[PinClass],
        via_wire_id: str,
        to_pin_obj: List[PinClass],
    ) -> None:
        via_wire_obj = self.wire_objects[via_wire_id]
        self._connections.append(Connection(from_pin_obj, via_wire_obj, to_pin_obj))

    def compute_qty_multipliers(self):
        # do not run before all connections in harness have been made!
        total_length = sum(
            [
                wire.length.number if wire.length else 0
                for wire in self.wire_objects.values()
            ]
        )
        qty_multipliers_computed = {
            "WIRECOUNT": len(self.wire_objects),
            "TERMINATIONS": 999,  # TODO
            "LENGTH": self.length.number if self.length else 0,
            "TOTAL_LENGTH": total_length,
        }
        for subitem in self.additional_components:
            if isinstance(subitem.qty_multiplier, QtyMultiplierCable):
                computed_factor = qty_multipliers_computed[subitem.qty_multiplier.name]
                # inherit component's length unit if appropriate
                if subitem.qty_multiplier.name in ["LENGTH", "TOTAL_LENGTH"]:
                    if subitem.qty.unit is not None:
                        raise Exception(
                            f"No unit may be specified when using"
                            f"{subitem.qty_multiplier} as a multiplier"
                        )
                    subitem.qty = NumberAndUnit(subitem.qty.number, self.length.unit)

            elif isinstance(subitem.qty_multiplier, QtyMultiplierConnector):
                raise Exception("Used a connector multiplier in a cable!")
            else:  # int or float
                computed_factor = subitem.qty_multiplier
            subitem._qty_multiplier_computed = computed_factor


@dataclass
class MatePin:
    from_: PinClass
    to: PinClass
    arrow: Arrow


@dataclass
class MateComponent:
    from_: str  # Designator
    to: str  # Designator
    arrow: Arrow
