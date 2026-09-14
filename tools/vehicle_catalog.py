"""Canonical vehicle types used by the private intake."""
from __future__ import annotations
import re
from dataclasses import dataclass

class IntakeError(ValueError):
    pass

def slug(value):
    return re.sub(r'^-+|-+$', '', re.sub(r'[^a-z0-9]+', '-', value.strip().lower()))

@dataclass(frozen=True)
class Vehicle:
    make: str
    model: str
    model_year: int | None
    generation: int | None
    platform: str | None = None

    @property
    def known(self):
        return self.make != 'Unknown' and self.model != 'Unknown' and self.model_year is not None

    @property
    def vehicle_type(self):
        return f'{slug(self.make)}-{slug(self.model)}' + (f'-gen{self.generation}' if self.generation else '') if self.known else 'unidentified'

    @property
    def year_key(self):
        return str(self.model_year) if self.model_year else 'unknown-year'

    def as_dict(self):
        return dict(make=self.make, model=self.model, model_year=self.model_year,
                    generation=self.generation, platform=self.platform, vehicle_type=self.vehicle_type)

def canonical_vehicle(data, *, allow_unknown=True):
    if not isinstance(data, dict):
        raise IntakeError('Vehicle identity must be an object.')
    make, model = str(data.get('make') or '').strip(), str(data.get('model') or '').strip()
    year, generation = data.get('model_year', data.get('year')), data.get('generation')
    if not make or not model or year is None or slug(make) == 'unknown' or slug(model) == 'unknown':
        if allow_unknown:
            return Vehicle('Unknown', 'Unknown', None, None)
        raise IntakeError('Make, model and model year are required.')
    if len(make) > 80 or len(model) > 80 or not slug(make) or not slug(model):
        raise IntakeError('Invalid make or model.')
    if isinstance(year, bool) or not str(year).isdigit() or not 1886 <= int(year) <= 2100:
        raise IntakeError('Invalid model year.')
    year = int(year)
    if generation is not None:
        if isinstance(generation, bool) or not str(generation).isdigit() or not 1 <= int(generation) <= 99:
            raise IntakeError('Invalid generation.')
        generation = int(generation)
    aliases = {'chevy':'Chevrolet','chevrolet':'Chevrolet','opel':'Opel','vauxhall':'Vauxhall','cadillac':'Cadillac'}
    make = aliases.get(slug(make), make)
    platform = None
    if make == 'Chevrolet' and slug(model) == 'volt':
        model, platform = 'Volt', 'GM Voltec'
        derived = 1 if 2011 <= year <= 2015 else 2 if 2016 <= year <= 2019 else None
        if derived is None: raise IntakeError('Volt model year must be 2011–2019.')
    elif make in ('Opel','Vauxhall') and slug(model) == 'ampera':
        model, platform, derived = 'Ampera', 'GM Voltec', 1
        if not 2012 <= year <= 2015: raise IntakeError('Unsupported Ampera model year.')
    elif make == 'Cadillac' and slug(model) == 'elr':
        model, platform, derived = 'ELR', 'GM Voltec', 1
        if not 2014 <= year <= 2016: raise IntakeError('Unsupported ELR model year.')
    else:
        derived = generation
    if generation is not None and generation != derived:
        raise IntakeError('Generation conflicts with model year.')
    return Vehicle(make, model, year, derived, platform)
