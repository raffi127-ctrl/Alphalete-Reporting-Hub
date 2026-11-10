"""Which language a customer gets texted in.

Carlos 2026-11-09: "if a customer has a spanish name we need to start
sending the texts in spanish". The only thing we know about a customer
before the first text is the name on the order, so this is a NAME test: any
word of the name that is a common Spanish/Latino given name or surname ->
"es", else "en". It will misfire on some English-speaking customers with a
Hispanic surname; LANGUAGE_OVERRIDES (lower-cased full name -> "en"/"es")
pins the ones Carlos or Taylor correct by hand.

    >>> language("Yesenia Cordero")
    'es'
    >>> language("Thomas Blake")
    'en'
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict

# full name, lower-cased and accent-stripped -> "en" | "es"
LANGUAGE_OVERRIDES: Dict[str, str] = {}

SURNAMES = set("""
aguilar aguirre alvarado alvarez amaya andrade aparicio aquino arellano arias
arredondo arriaga avila ayala baez barajas barrera barrios bautista becerra
beltran benitez bermudez bernal bonilla bravo briones bustamante caballero
cabrera calderon camacho campos canales cano cantu cardenas carranza carrasco
carrillo casillas castaneda castellanos castillo castro cazares ceballos
cervantes chavarria chavez choc cisneros colon contreras cordero cordova corona
coronado cortes cortez cruz cuevas davila de la cruz de la rosa de la torre
deleon delgado diaz dominguez duarte duran echeverria elizondo enriquez
escalante escamilla escobar escobedo espinoza espinosa esquivel estrada
fajardo farias fernandez fierro figueroa flores fonseca franco fuentes galindo
gallegos galvan galvez gamboa gamez garay garcia garibay garza gaytan
gonzales gonzalez granados guajardo guerra guerrero guevara gutierrez guzman
haro henriquez heredia hernandez herrera hidalgo hinojosa huerta hurtado
ibarra iglesias jaramillo jasso jimenez juarez lara leal ledesma leon leyva
limon linares lira lopez loera lozano lugo luna macias madrigal maldonado
mares marin marquez marroquin martinez mata medina medrano mejia melendez
mendez mendoza meza miranda molina mondragon monroy montalvo montano montes
montoya mora morales moreno munoz murillo najera naranjo nava navarrete
navarro nieto nunez ocampo ochoa ojeda olivares olivas olvera ontiveros
ordonez orellana ornelas orozco ortega ortiz osorio pacheco padilla palacios
palomino pantoja paredes parra pedraza pena peralta perez pineda pina pinedo
piedra ponce portillo prado puente quezada quinones quintanilla quintero
quiroz ramirez ramos rangel rendon renteria reyes reyna rincon rios rivas
rivera robledo robles rocha rodriguez rojas roldan romero rosales rosas rubio
ruiz saenz salas salazar salcedo saldana salgado salinas sanchez sandoval
santana santiago santos saucedo segovia segura sepulveda serna serrano sierra
silva solano solis soliz soto suarez tamayo tapia tejada tellez terrazas
toledo torres tovar trejo trevino trujillo urbina urena uribe valadez valdez
valdes valencia valenzuela valle vallejo varela vargas vasquez vazquez vega
vela velasco velasquez velazquez velez venegas vera verduzco villa villalobos
villanueva villarreal villegas yanez ybarra zamora zapata zaragoza zarate
zavala zepeda zuniga vertiz garces villareal lacayo conde
""".split())

GIVEN = set("""
abel adriana agustin alba alberto alejandra alejandro alfonso alfredo alicia
alma alonso amado ana andrea andres angel angela angelica antonio araceli
armando arturo aurora beatriz belen benito berenice bernardo blanca brenda
carlos carmen carolina catalina cecilia celia cesar cinthya cintia claudia
concepcion consuelo cristian cristina cristobal dania daniela david diego
dolores domingo dulce edgar eduardo efrain elena elias eliseo elizabeth
eloy elvira emilio emmanuel enrique erika ernesto esmeralda esperanza esteban
estela eugenio eva fabiola federico felipe felix fernanda fernando fidel
francisca francisco gabriel gabriela gerardo gilberto gloria gonzalo graciela
guadalupe guillermo gustavo hector heriberto hilda horacio hugo humberto
ignacio ines irma isabel isidro ismael israel ivan jacinto jaime javier
jesus joaquin jorge jose josefina josue juan juana julia julio karla kennir
leonardo leonel leticia lidia lilia liliana lorena lorenzo lourdes lucia
luis luisa lupe luz magdalena manuel marcela marcelino marco marcos margarita
maria mariana maribel maricela mario marisol marta martha martin mateo
mauricio maximiliano mayra mercedes miguel mireya moises monica nancy
natalia nayeli nestor noe noemi norma octavio ofelia olga omar oscar pablo
paola patricia pedro perla petra rafael ramiro ramon raquel raul rebeca
refugio reyna ricardo rigoberto roberto rocio rodolfo rodrigo rogelio rolando
rosa rosalba rosario ruben salvador samuel sandra santiago santos saraid
saul sergio silvia socorro sofia soledad susana teresa tomas ulises valentin
valeria veronica vicente victor victoria virginia xavier xochitl yadira
yahir yesenia yeymi yolanda yesica zoila amada arianna cornelio
""".split())


def _words(name: str):
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return [w for w in re.split(r"[^a-z]+", s) if w]


def is_spanish_name(name: str) -> bool:
    """True when any word of the name is a common Spanish given name or
    surname (accents and case ignored)."""
    return any(w in SURNAMES or w in GIVEN for w in _words(name))


def language(name: str) -> str:
    """'es' or 'en' for this customer name, overrides first."""
    key = " ".join(_words(name))
    if key in LANGUAGE_OVERRIDES:
        return LANGUAGE_OVERRIDES[key]
    return "es" if is_spanish_name(name) else "en"
