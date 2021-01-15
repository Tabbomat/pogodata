import re

from .util import httpget, POKEMON_TYPES
from .game_objects import make_type_list, make_item_list
from .moves import make_move_list
from .grunts import make_grunt_list

from .mons import Pokemon

PROTO_URL = "https://raw.githubusercontent.com/Furtif/POGOProtos/master/base/base.proto"
GAMEMASTER_URL = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json"
LOCALE_URL = "https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/Texts/Latest%20APK/JSON/i18n_{lang}.json"

class PogoData:
    """The class holding all data this module provides

    Parameters
    ----------
    language: :class:`str`
        The language used for translations. Default: english
        Available languages: https://github.com/PokeMiners/pogo_assets/tree/master/Texts/Latest%20APK/JSON
    icon_url: :class:`str`
        An URL to the base of an UIcons-compatible icon repo for UIcon support.

    Attributes
    ----------
    mons: List[:class:`.Pokemon`]
        All Pokémon.
    items: List[:class:`.items.Item`]
        All Items.
    types: List[:class:`.types.Type`]
        All available Pokémon Types.
    moves: List[:class:`.moves.Move`]
        All Moves.
    grunts: List[:class:`.grunts.Grunt`]
        All Grunts.
    """
    def __init__(self, language="english", icon_url=""):
        self.__cached_enums = {}
        self.icon_url = icon_url
        self.reload(language)

    def reload(self, language="english"):
        """Reloads all data, as if you'd re-initialize the class.

        Parameters
        ----------
        language: :class:`str`
            The language used for translations. Default: english
            Available languages: https://github.com/PokeMiners/pogo_assets/tree/master/Texts/Latest%20APK/JSON
        """
        self.raw_protos = httpget(PROTO_URL).text
        self.raw_gamemaster = httpget(GAMEMASTER_URL).json()

        raw_locale = httpget(LOCALE_URL.format(lang=language.lower())).json()["data"]
        self.locale = {}
        for i in range(0, len(raw_locale), 2):
            self.locale[raw_locale[i]] = raw_locale[i+1]

        self.items = make_item_list(self)
        self.types = make_type_list(self)
        self.moves = make_move_list(self)
        self.grunts = make_grunt_list(self)

        self.__make_mon_list()

    def __get_object(self, obj_list, args, match_one=True):
        final = []
        for obj in obj_list:
            wanted = True
            for key, value in args.items():
                if obj.__dict__.get(key) != value:
                    wanted = False

            if wanted:
                if match_one:
                    return obj
                final.append(obj)

        if not match_one:
            return final

        return None

    def get_mon(self, get_one=True, **args):
        mon = self.__get_object(self.mons, args, get_one)
        if args.get("costume", 0) > 0:
            mon = mon.copy()
            mon.costume = args["costume"]
            mon._gen_asset()

        return mon

    def get_type(self, **args):
        if "template" in args:
            if not args["template"].startswith("POKEMON_TYPE_"):
                args["template"] = "POKEMON_TYPE_" + args["template"]
        return self.__get_object(self.types, args)

    def get_item(self, **args):
        return self.__get_object(self.items, args)

    def get_move(self, **args):
        return self.__get_object(self.moves, args)

    def get_grunt(self, **args):
        return self.__get_object(self.grunts, args)

    def get_locale(self, key):
        return self.locale.get(key.lower(), "?")

    def get_enum(self, enum, reverse=False):
        cached = self.__cached_enums.get(enum.lower())
        if cached:
            return cached

        proto = re.findall(f"enum {enum} "+r"{[^}]*}", self.raw_protos, re.IGNORECASE)
        if len(proto) == 0:
            raise KeyError(f"Could not find Enum {enum}")

        proto = proto[0].replace("\t", "")

        final = {}
        proto = proto.split("{\n")[1].split("\n}")[0]
        for entry in proto.split("\n"):
            k = entry.split(" =")[0]
            v = int(entry.split("= ")[1].split(";")[0])
            final[k] = v

        self.__cached_enums[enum.lower()] = final

        if reverse:
            final = {value:key for key, value in final.items()}

        return final

    def get_gamemaster(self, pattern, settings=None):
        result = []
        for entry in self.raw_gamemaster:
            templateid = entry.get("templateId", "")
            if re.search(pattern, templateid):
                data = entry.get("data", {})
                if settings:
                    data = data.get(settings, {})

                result.append((
                    templateid, data
                ))
        return result

    # Build lists

    def __make_mon_list(self):
        def __typing(mon, type1ref, type2ref):
            typings = [mon.raw.get(type1ref), mon.raw.get(type2ref)]
            for typing in typings:
                if typing:
                    mon.types.append(self.get_type(template=typing))

        self.mons = []
        forms = self.get_enum("Form")
        megas = self.get_enum("HoloTemporaryEvolutionId")
        mon_ids = self.get_enum("HoloPokemonId")

        # Creating a base mon list based on GM entries
        pattern = r"^V\d{4}_POKEMON_"
        for templateid, entry in self.get_gamemaster(pattern+".*", "pokemonSettings"):
            template = re.sub(pattern, "", templateid)
            form_id = forms.get(template, 0)
            mon_id = mon_ids.get(template, 0)
            mon = Pokemon(entry, form_id, template, mon_id)

            locale_key = "pokemon_name_" + str(mon.id).zfill(4)
            mon.name = self.get_locale(locale_key)

            mon.quick_moves = [self.get_move(template=t) for t in mon.raw.get("quickMoves", [])]
            mon.charge_moves = [self.get_move(template=t) for t in mon.raw.get("cinematicMoves", [])]

            __typing(mon, "type", "type2")

            self.mons.append(mon)

            # Handling Temp (Mega) Evolutions
            for temp_evo in mon.raw.get("tempEvoOverrides", []):
                evo = mon.copy()
                evo.type = POKEMON_TYPES[2]

                evo.temp_evolution_template = temp_evo.get("tempEvoId")
                evo.temp_evolution_id = megas.get(evo.temp_evolution_template)

                evo.raw = temp_evo
                evo.name = self.get_locale(locale_key + "_" + str(evo.temp_evolution_id).zfill(4))
                evo._make_stats()

                evo.types = []
                __typing(evo, "typeOverride1", "typeOverride2")

                self.mons.append(evo)
                mon.temp_evolutions.append(evo)

        # Going through GM Forms and adding missing Forms (Unown, Spinda) and making in-game assets
        form_enums = self.get_enum("Form")
        for template, formsettings in self.get_gamemaster(r"^FORMS_V\d{4}_POKEMON_.*", "formSettings"):
            forms = formsettings.get("forms", [])
            for form in forms:
                mon = self.get_mon(template=form.get("form"))
                if not mon:
                    mon = self.get_mon(template=formsettings["pokemon"])
                    mon = mon.copy()
                    mon.type = POKEMON_TYPES[1]
                    mon.template = form.get("form")
                    mon.form = form_enums.get(mon.template)
                    self.mons.append(mon) 

                asset_value = form.get("assetBundleValue")
                asset_suffix = form.get("assetBundleSuffix")
                if asset_value or asset_suffix:
                    mon.asset_value = asset_value
                    mon.asset_suffix = asset_suffix
                    mon._gen_asset()

        # Temp Evolution assets
        evo_gm = self.get_gamemaster(
            r"^TEMPORARY_EVOLUTION_V\d{4}_POKEMON_.*",
            "temporaryEvolutionSettings"
        )
        for base_template, evos in evo_gm:
            base_template = evos.get("pokemonId", "")
            evos = evos.get("temporaryEvolutions", [])
            for temp_evo_raw in evos:
                mon = self.get_mon(
                    base_template=base_template,
                    temp_evolution_template=temp_evo_raw["temporaryEvolutionId"]
                )
                mon.asset_value = temp_evo_raw["assetBundleValue"]
                mon._gen_asset()

        # Making Pokemon.evolutions attributes
        for mon in self.mons:
            evolutions = mon.raw.get("evolutionBranch", [])
            for evo_raw in evolutions:
                if "temporaryEvolution" in evo_raw:
                    continue
                evo = self.get_mon(
                    template=evo_raw.get("form", evo_raw["evolution"])
                )
                mon.evolutions.append(evo)
