"""Physical dimensions and SVG asset helpers for draft layout conversion."""
from pathlib import Path
import re,hashlib,shutil
PHYSICAL_UNITS={"MM","Point","Points","Inch","Inches","Pixel","Pixels"}

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def multiply(value, factor):
    """Scale numeric dimensions, including comma/semicolon separated offsets."""
    return re.sub(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',
                  lambda m: format(float(m.group()) * factor, '.15g'), value)

def scale_measure(value, factor, offset=None):
    parts = value.split(',')
    if parts[-1] != 'mm':
        raise ValueError('Expected millimetre layout geometry: ' + value)
    numbers = [float(v) * factor for v in parts[:-1]]
    if offset is not None:
        numbers = [v + delta for v, delta in zip(numbers, offset)]
    return ','.join([*(format(v, '.15g') for v in numbers), 'mm'])

def scale_physical_styles(root, factor):
    """Scale millimetre symbols/halos without changing colours or map units."""
    for element in root.iter():
        if element.tag == 'Option' and element.get('type') == 'Map':
            options = {child.get('name'): child for child in element.findall('./Option')}
            for key, unit in options.items():
                if not key or unit.get('value') not in PHYSICAL_UNITS:
                    continue
                for suffix in ('_unit', '_units'):
                    if key.endswith(suffix) and key[:-len(suffix)] in options:
                        item = options[key[:-len(suffix)]]
                        item.set('value', multiply(item.get('value', '0'), factor))
                        break
        pairs = {
            'bufferSizeUnits': ['bufferSize'],
            'maskSizeUnits': ['maskSize', 'maskSize2'],
            'shapeSizeUnit': ['shapeSizeX', 'shapeSizeY'],
            'shapeOffsetUnit': ['shapeOffsetX', 'shapeOffsetY'],
            'shapeRadiiUnit': ['shapeRadiiX', 'shapeRadiiY'],
            'shapeBorderWidthUnit': ['shapeBorderWidth'],
            'shadowOffsetUnit': ['shadowOffsetDist'],
            'shadowRadiusUnit': ['shadowRadius'],
            'distUnits': ['dist'], 'offsetUnits': ['xOffset', 'yOffset'],
            'repeatDistanceUnits': ['repeatDistance'],
            'overrunDistanceUnit': ['overrunDistance'],
            'maximumDistanceUnit': ['maximumDistance'],
            'fontSizeUnit': ['fontLetterSpacing', 'fontWordSpacing'],
        }
        for unit_name, dimensions in pairs.items():
            if element.get(unit_name) in PHYSICAL_UNITS:
                for key in dimensions:
                    if key in element.attrib:
                        element.set(key, multiply(element.get(key), factor))

def collect_assets(root, context, output):
    """Copy SVGs used by the working layout; keep source resources read-only."""
    assets = output / 'assets'
    records = []
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if not value.lower().endswith('.svg'):
                continue
            source = Path(context.pathResolver().readPath(value)).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            assets.mkdir(exist_ok=True)
            target = assets / (digest(source)[:10] + '_' + source.name)
            if not target.exists():
                shutil.copy2(source, target)
            element.set(key, str(target))
            records.append({'source': str(source), 'copy': str(target),
                            'sha256': digest(source)})
    return records
