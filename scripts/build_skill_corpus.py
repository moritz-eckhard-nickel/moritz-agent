# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Write tests/moritz_agent/data/skills.de.jsonl from the phrase lists below (SKILL-27).

Every line: {"say": sentence, "skill": expected skill id or null, "prior": [sentences said before]}.
Run ``python scripts/build_skill_corpus.py`` after changing the lists; the corpus test replays it.
"""

from __future__ import annotations

import json
from pathlib import Path

POSITIVE: dict[str, list[str]] = {
    "time.now": [
        "Wie viel Uhr ist es?",
        "Wie spät ist es?",
        "Wie viel Uhr haben wir?",
        "Wie spät isses?",
        "Wie viel Uhr hammer?",
        "Uhrzeit?",
        "Welche Uhrzeit haben wir?",
        "Sag mir die Uhrzeit",
        "Kannst du mir sagen, wie spät es ist?",
        "Nikita, wie viel Uhr ist es?",
        "Weißt du, wie spät es ist?",
        "Wie spät ist es gerade?",
        "Wieviel Uhr ist es denn?",
        "Wie spät iss es?",
        "Hey Nikita wie spät ist es",
        "Sag mal, wie viel Uhr haben wir eigentlich?",
        "Ich möchte wissen, wie spät es ist",
        "Jetzt mal ehrlich, wie spät ist es?",
    ],
    "time.datetime": ["Datum und Uhrzeit?", "Uhrzeit und Datum bitte", "Sag mir Datum und Uhrzeit"],
    "time.world": [
        "Wie spät ist es in New York?",
        "Uhrzeit in Tokio?",
        "Wie viel Uhr ist es in London?",
        "Wie spät ist es in Sydney gerade?",
        "Wie viel Uhr ist es in Madrid?",
        "Was ist die Uhrzeit in Los Angeles?",
    ],
    "time.offset": [
        "Wie viel Zeitunterschied ist es nach Sydney?",
        "Zeitverschiebung nach New York?",
    ],
    "time.in_duration": [
        "Wie spät ist es in drei Stunden?",
        "Wie spät ist es in 90 Minuten?",
        "Wann ist es in einer halben Stunde?",
    ],
    "time.until": [
        "Wie lange noch bis 22 Uhr?",
        "Wie lange ist es noch bis Mitternacht?",
        "Wie lange noch bis 23:30?",
    ],
    "time.dst_now": ["Haben wir gerade Sommerzeit?", "Haben wir schon Winterzeit?"],
    "time.dst_next": [
        "Wann wird die Uhr umgestellt?",
        "Zeitumstellung?",
        "Wann ist die nächste Zeitumstellung?",
        "Wann wird die Uhr zurückgestellt?",
    ],
    "date.today": [
        "Welches Datum ist heute?",
        "Der Wievielte ist heute?",
        "Welches Datum haben wir?",
        "Was hammer heit fürn Datum?",
        "Welches Datum haben wir heute?",
        "Sag mir das heutige Datum",
        "Den Wievielten haben wir heute?",
    ],
    "date.weekday": [
        "Welcher Tag ist heute?",
        "Welcher Wochentag ist heute?",
        "Was ist heute für ein Tag?",
        "Welchen Wochentag haben wir?",
    ],
    "date.relative": [
        "Welcher Tag ist morgen?",
        "Welches Datum ist morgen?",
        "Welcher Tag war gestern?",
        "Welcher Tag ist übermorgen?",
        "Welcher Wochentag ist morgen?",
        "Welches Datum war gestern?",
        "Welcher Wochentag war vorgestern?",
    ],
    "date.weekday_of": [
        "Was für ein Tag ist der 24. Dezember?",
        "Welcher Wochentag war der 3. Oktober 1990?",
        "Auf welchen Tag fällt der 1. Mai?",
    ],
    "date.offset": [
        "Welches Datum ist in drei Wochen?",
        "Welches Datum ist in 100 Tagen?",
        "Welcher Tag ist in 2 Monaten?",
    ],
    "date.days_until": [
        "Wie viele Tage noch bis Weihnachten?",
        "Wie viele Tage bis Silvester?",
        "Wie lange noch bis Weihnachten?",
        "Wie viele Tage bis zum Wochenende?",
        "Wie viele Tage sind es noch bis Ostern?",
        "Wie viele Tage bis zum 1. März?",
        "Wie viele Tage bis Neujahr?",
        "Wie viele Tage bis zu den Weihnachtsferien?",
        "Wie viele Wochen bis Weihnachten?",
        "Wie viele Tage noch bis zum ersten Advent?",
        "Noch wie viele Tage bis Heiligabend?",
    ],
    "date.days_since": [
        "Wie viele Tage sind seit Neujahr vergangen?",
        "Wie lange ist der 1. Mai her?",
    ],
    "date.between": [
        "Wie viele Tage liegen zwischen dem 1. März und dem 15. April?",
        "Wie viele Tage vom 1. Januar bis zum 1. März?",
    ],
    "date.calendar_week": [
        "Welche Kalenderwoche haben wir?",
        "Welche KW haben wir?",
        "In welcher Kalenderwoche sind wir?",
        "Welche Woche ist gerade?",
    ],
    "date.week_range": ["Wann ist KW 50?", "Kalenderwoche 10"],
    "date.day_of_year": [
        "Der wievielte Tag des Jahres ist heute?",
        "Wie viele Tage hat das Jahr noch?",
    ],
    "date.month_info": ["Wie viele Tage hat der Februar 2028?", "Wie viele Tage hat der November?"],
    "date.leap_year": ["Ist 2028 ein Schaltjahr?", "Ist dieses Jahr ein Schaltjahr?"],
    "date.age": [
        "Wie alt ist jemand, der am 12. Mai 1990 geboren ist?",
        "Wie alt bin ich, wenn ich 1995 geboren bin?",
    ],
    "date.special": [
        "Wann ist Muttertag?",
        "Wann ist der erste Advent?",
        "Wann ist Ostern 2027?",
        "Wann ist Rosenmontag?",
        "Wann ist Erntedank?",
        "Wann ist Vatertag?",
    ],
    "holiday.next": [
        "Wann ist der nächste Feiertag?",
        "Nächster Feiertag?",
        "Wann ist wieder Feiertag?",
    ],
    "holiday.is": [
        "Ist morgen ein Feiertag?",
        "Ist heute Feiertag?",
        "Haben wir morgen Feiertag?",
        "Ist der 3. Oktober ein Feiertag?",
        "Ist der 1. Mai in Hessen ein Feiertag?",
        "Ist Fronleichnam in Bayern ein Feiertag?",
        "Ist Allerheiligen in NRW ein Feiertag?",
        "Ist der Reformationstag in Sachsen ein Feiertag?",
    ],
    "holiday.list": [
        "Welche Feiertage gibt es im Dezember?",
        "Welche Feiertage haben wir noch?",
        "Feiertage 2027?",
    ],
    "holiday.long_weekend": ["Wann ist das nächste lange Wochenende?", "Brückentage?"],
    "holiday.workdays": ["Wie viele Arbeitstage hat der November?", "Arbeitstage bis Weihnachten?"],
    "school.next": [
        "Wann sind die nächsten Ferien?",
        "Wann sind Sommerferien?",
        "Wann sind die Weihnachtsferien?",
        "Wann beginnen die Osterferien 2027?",
    ],
    "school.now": ["Sind gerade Ferien?", "Haben wir Ferien?", "Sind morgen Ferien?"],
    "calc.arith": [
        "Was ist 17 mal 23?",
        "144 geteilt durch 12",
        "2 hoch 10",
        "Wurzel aus 144",
        "Was ist 7 plus 8?",
        "Was ist 100 minus 37?",
        "Wie viel ist 12 mal 12",
        "Rechne 15 plus 27",
        "Was ist siebzehn mal dreiundzwanzig?",
        "3 zum Quadrat",
        "(3 plus 4) mal 5",
        "1000 geteilt durch 8",
    ],
    "calc.percent": [
        "Was sind 19 Prozent von 249?",
        "Wie viel Prozent sind 30 von 120?",
        "20 Prozent von 80",
        "Was sind 7 Prozent von 1200 Euro?",
        "15 % von 60",
    ],
    "calc.vat": [
        "Was sind 100 Euro netto brutto?",
        "Wie viel Mehrwertsteuer ist in 59,90 Euro?",
        "100 Euro brutto in netto",
        "Mehrwertsteuer auf 200 Euro",
    ],
    "calc.tip": ["10 Prozent Trinkgeld auf 43 Euro?", "Wie viel Trinkgeld bei 87 Euro?"],
    "calc.split": ["86 Euro durch 3 Personen", "240 Euro durch 4 Leute"],
    "calc.fraction": ["Was ist ein Drittel von 90?", "Die Hälfte von 150", "Ein Viertel von 200"],
    "calc.discount": ["Was kostet 80 Euro minus 25 Prozent?", "80 Euro mit 25 Prozent Rabatt"],
    "calc.round": ["Runde 3,14159 auf 2 Stellen"],
    "convert.units": [
        "Wie viel sind 5 Meilen in Kilometer?",
        "100 Fahrenheit in Celsius",
        "Wie viele Gramm sind ein Pfund?",
        "3 Esslöffel in Milliliter",
        "50 Knoten in km/h",
        "Wie viele Sekunden hat ein Tag?",
        "10 Zoll in Zentimeter",
        "2 Gigabyte in Megabyte",
        "Wie viele Meter sind 3 Kilometer?",
    ],
    "convert.numeral": ["Was ist 2026 in römischen Zahlen?", "42 in binär?"],
    "spell.word": ["Buchstabier Weilburg", "Wie buchstabiert man Lahn?", "Buchstabiere mir Nikita"],
    "random.coin": ["Wirf eine Münze", "Kopf oder Zahl?"],
    "random.dice": ["Würfel mal", "Wirf zwei Würfel", "Würfel einen W20"],
    "random.number": ["Nenn mir eine Zahl zwischen 1 und 100", "Zufallszahl"],
    "random.choice": ["Entscheide Pizza oder Döner"],
    "fun.joke": ["Erzähl einen Witz", "Kennst du einen Witz?", "Sag was Lustiges"],
    "fun.hessian": ["Sag was auf Hessisch", "Was heißt Guude?"],
    "count.down": ["Zähl von 10 runter"],
    "timer.start": ["Stell einen Timer auf 3 Minuten", "Eieruhr 7 Minuten", "Timer für 10 Minuten"],
    "remind.add": [
        "Erinnere mich morgen um 8 an den Zahnarzt",
        "Erinner mich in 2 Stunden an die Wäsche",
        "Kannst du mich heute Abend um 20 Uhr an Anna erinnern",
        "Erinnere mich am Freitag um 15 Uhr daran, Moritz anzurufen",
    ],
    "talk.goodbye": [
        "Tschüss",
        "Auf Wiederhören",
        "Danke, das war's",
        "Ade",
        "Tschau",
        "Bis bald",
        "Gute Nacht",
        "Auflegen",
        "Tschüss Nikita",
    ],
    "talk.greeting": ["Guude!", "Hallo", "Moin", "Servus", "Hallo Nikita", "Guten Tag"],
    "talk.thanks": ["Danke", "Vielen Dank", "Super, danke", "Danke schön", "Merci"],
    "talk.how_are_you": ["Wie geht's dir?", "Wie geht es dir?", "Alles klar bei dir?", "Wie gehts"],
    "talk.identity": [
        "Wer bist du?",
        "Wie heißt du?",
        "Stell dich vor",
        "Bist du ein Mensch?",
        "Bist du eine KI?",
    ],
    "talk.help": [
        "Was kannst du?",
        "Hilfe",
        "Was kann ich dich fragen?",
        "Wobei kannst du helfen?",
    ],
    "talk.repeat": [
        "Was hast du gesagt?",
        "Kannst du das wiederholen?",
        "Nochmal bitte",
        "Wie bitte?",
    ],
    "talk.slower": [
        "Sprich langsamer",
        "Etwas schneller bitte",
        "Kannst du etwas langsamer sprechen",
    ],
    "talk.louder": ["Lauter bitte", "Leiser"],
    "talk.call_duration": ["Wie lange telefonieren wir schon?"],
    "talk.hear_me": ["Hörst du mich?", "Bist du noch da?"],
    "talk.privacy": ["Speicherst du das?", "Nimmst du das auf?", "Wird das aufgezeichnet?"],
    "talk.version": ["Welche Version hast du?", "Wie lange läufst du schon?"],
    "talk.status": ["Läuft alles?", "Systemstatus?"],
    "talk.cancel": ["Vergiss es", "Abbrechen"],
    "briefing": ["Guten Morgen", "Was steht heute an?", "Gib mir einen Überblick"],
}

# places and weather (P1-21, P1-22): online skills answer "no connection" in the corpus test, which
# is enough to check that the right skill is chosen
POSITIVE.update(
    {
        "geo.plz_to_place": [
            "Wo ist 35781?",
            "Welcher Ort hat die Postleitzahl 65549?",
            "Zu welchem Ort gehört die PLZ 60311?",
        ],
        "geo.place_to_plz": [
            "Welche Postleitzahl hat Limburg?",
            "Welche PLZ hat Weilburg?",
            "Postleitzahl von Wetzlar",
        ],
        "geo.distance": [
            "Wie weit ist es nach Frankfurt?",
            "Entfernung Weilburg Gießen",
            "Wie weit ist Berlin von München entfernt?",
            "Wie weit ist es bis Köln?",
        ],
        "geo.region_of": [
            "In welchem Bundesland liegt Wetzlar?",
            "Zu welchem Kreis gehört Runkel?",
        ],
        "geo.home": [
            "Wo bin ich?",
            "Was ist mein Standort?",
            "Für welchen Ort sagst du das Wetter?",
        ],
        "weather.now": [
            "Wie ist das Wetter?",
            "Wie isses Wedder drauße?",
            "Wie ist das Wetter in Berlin?",
            "Wetter in 60311",
            "Nikita, wie ist das Wetter gerade?",
            "Wie ist das Wetter bei uns?",
            "Sag mal, wie ist eigentlich das Wetter?",
            "Wetter?",
            "Wie ist das Wetter in Weilborg?",
        ],
        "weather.region": ["Wie ist das Wetter in der Region?", "Wie warm ist es im Landkreis?"],
        "weather.today": ["Wie wird das Wetter heute?", "Wie werd's heit?", "Wetter heute"],
        "weather.daypart": [
            "Wie wird es heute Abend?",
            "Wie wird das Wetter heute Nacht?",
            "Wie ist das Wetter morgen früh?",
            "Wie wird das Wetter morgen Nachmittag?",
        ],
        "weather.day": [
            "Wie wird das Wetter morgen?",
            "Wie wird das Wetter übermorgen?",
            "Wetter am Samstag",
            "Wie wird das Wetter am Freitag in Limburg?",
            "Wie wird's morsche?",
        ],
        "weather.weekend": [
            "Wie wird das Wetter am Wochenende?",
            "Wetter am Wochenende in Frankfurt",
        ],
        "weather.week": [
            "Wie wird die Woche?",
            "Wetter für die nächsten Tage",
            "Wie wird das Wetter nächste Woche?",
        ],
        "weather.hour": [
            "Wie ist das Wetter um 15 Uhr?",
            "Wie wird das Wetter in zwei Stunden?",
        ],
        "weather.long_range": [
            "Wie wird das Wetter in zwei Wochen?",
            "Wie wird das Wetter in 20 Tagen?",
        ],
        "weather.yesterday": ["Wie war das Wetter gestern?", "Wie war das Wetter vorgestern?"],
        "weather.rain": ["Regnet es heute?", "Gibt's Regen?", "Wird's nass?", "Regnet es morgen?"],
        "weather.rain_when": [
            "Wann fängt es an zu regnen?",
            "Wann hört der Regen auf?",
            "Wie lange regnet es noch?",
        ],
        "weather.rain_now": ["Regnet es gerade?", "Regnet es draußen?"],
        "weather.rain_amount": ["Wie viel Regen kommt?", "Wie viel hat es geregnet?"],
        "weather.umbrella": [
            "Brauche ich einen Schirm?",
            "Brauch isch en Schermche?",
            "Brauche ich morgen einen Regenschirm?",
        ],
        "weather.snow": [
            "Schneit es morgen?",
            "Gibt es weiße Weihnachten?",
            "Wird es Schnee geben?",
        ],
        "weather.frost": [
            "Gibt es heute Nacht Frost?",
            "Muss ich morgen kratzen?",
            "Wird es glatt?",
            "Gibt es Glatteis?",
        ],
        "weather.wind": [
            "Wie windig ist es?",
            "Gibt es Sturm?",
            "Wie stark sind die Böen?",
            "Wie windig wird es morgen?",
        ],
        "weather.thunder": ["Gibt es Gewitter?", "Wird's heute gewittrig?", "Gewittert es morgen?"],
        "weather.fog": ["Ist es neblig?", "Gibt es morgen früh Nebel?"],
        "weather.visibility": ["Wie ist die Sicht?"],
        "weather.temperature": [
            "Wie warm ist es?",
            "Wie viel Grad hat es?",
            "Wie kalt wird es heute Nacht?",
            "Wie warm wird es morgen?",
            "Wieviel Grad sind es draußen?",
            "Wie heiß wird es am Mittwoch?",
        ],
        "weather.feels_like": ["Wie kalt fühlt es sich an?", "Wie ist die gefühlte Temperatur?"],
        "weather.humidity": ["Wie hoch ist die Luftfeuchtigkeit?", "Ist es schwül?"],
        "weather.pressure": ["Wie ist der Luftdruck?"],
        "weather.sunshine": ["Scheint heute die Sonne?", "Wie viele Sonnenstunden gibt es morgen?"],
        "weather.clouds": ["Ist es bewölkt?", "Ist der Himmel klar?"],
        "sky.stars": ["Kann man heute Nacht Sterne sehen?", "Sieht man heute Sterne?"],
        "weather.uv": ["Wie hoch ist der UV-Index?", "Brauche ich Sonnencreme?"],
        "weather.compare": [
            "Wird es morgen wärmer als heute?",
            "Ist es in Frankfurt wärmer als hier?",
            "Wird es morgen kälter als heute?",
        ],
        "weather.extremes": [
            "Wann ist es heute am wärmsten?",
            "Welcher Tag wird diese Woche am schönsten?",
        ],
        "weather.when_change": [
            "Wann wird es wieder warm?",
            "Wann kommt der nächste Frost?",
            "Wann wird es wieder trocken?",
        ],
        "weather.observed": ["Was misst die Wetterstation?", "Wie warm ist es wirklich?"],
        "weather.source": ["Welcher Wetterdienst?"],
    }
)

POSITIVE.update(
    {
        "warn.weather": [
            "Gibt es Unwetterwarnungen?",
            "Gibt's Warnungen für Weilburg?",
            "Gibt es Wetterwarnungen?",
            "Gibt es eine Unwetterwarnung heute?",
            "Warnt der Wetterdienst vor etwas?",
        ],
        "warn.civil": [
            "Gibt es Warnungen im Landkreis?",
            "Gibt es eine Katastrophenwarnung?",
        ],
        "pollen.today": [
            "Wie ist der Pollenflug?",
            "Fliegen heute Pollen?",
            "Wie sieht's mit Birke aus?",
            "Hab ich heute Heuschnupfen?",
        ],
        "pollen.forecast": ["Wie wird der Pollenflug morgen?", "Pollen übermorgen?"],
        "air.quality": ["Wie ist die Luftqualität?", "Wie ist die Luft?", "Wie ist der Feinstaub?"],
        "air.ozone": ["Wie hoch ist das Ozon?", "Ozon heute?"],
        "advice.jacket": [
            "Brauche ich eine Jacke?",
            "Was soll ich anziehen?",
            "Was soll ich morgen anziehen?",
        ],
        "advice.laundry": ["Kann ich Wäsche draußen aufhängen?", "Wäsche draußen trocknen heute?"],
        "advice.bbq": ["Ist heute Grillwetter?", "Kann ich heute grillen?"],
        "advice.bike": [
            "Ist Fahrradwetter?",
            "Kann ich mit dem Rad fahren?",
            "Kann ich morgen radeln?",
        ],
        "advice.run": ["Kann ich joggen gehen?", "Wann ist heute die beste Zeit zum Laufen?"],
        "advice.garden_water": ["Muss ich den Garten gießen?", "Muss ich die Tomaten gießen?"],
        "advice.mow": ["Kann ich Rasen mähen?"],
        "advice.ventilate": ["Soll ich lüften?", "Fenster auflassen heute Nacht?"],
        "advice.car_wash": ["Lohnt sich Autowaschen?", "Soll ich das Auto waschen?"],
        "advice.swim": ["Ist Badewetter?", "Kann man heute baden gehen?"],
        "advice.hike": ["Wie ist das Wetter zum Wandern am Samstag?", "Ist Wanderwetter?"],
        "advice.plants_frost": ["Muss ich die Pflanzen reinholen?"],
        "advice.heating": ["Wird es kalt genug zum Heizen?", "Ist heute ein Heiztag?"],
    }
)

POSITIVE.update(
    {
        "sun.rise_set": [
            "Wann geht die Sonne auf?",
            "Wann geht die Sonne unter?",
            "Wann ist morgen Sonnenaufgang in Berlin?",
            "Sonnenuntergang?",
            "Wann geht heute die Sonne unter?",
        ],
        "sun.dark": ["Wann wird es dunkel?", "Wann wird es hell?", "Ist es draußen noch hell?"],
        "sun.daylength": ["Wie lange ist es heute hell?", "Wie viel kürzer werden die Tage?"],
        "sun.noon": ["Wann steht die Sonne am höchsten?"],
        "sun.golden_hour": ["Wann ist die goldene Stunde?"],
        "sun.solstice": [
            "Ab wann werden die Tage wieder länger?",
            "Wann sind die Tage am kürzesten?",
            "Wann ist Wintersonnenwende?",
        ],
        "moon.phase": [
            "Welche Mondphase haben wir?",
            "Ist heute Vollmond?",
            "Wie sieht der Mond aus?",
        ],
        "moon.next": [
            "Wann ist der nächste Vollmond?",
            "Wann ist Neumond?",
            "Wann ist der nächste Halbmond?",
        ],
        "moon.rise_set": ["Wann geht der Mond auf?", "Wann geht der Mond unter?"],
        "season.start": [
            "Wann ist Frühlingsanfang?",
            "Wann beginnt der Winter?",
            "Wann fängt der Sommer an?",
        ],
    }
)

POSITIVE.update(
    {
        "money.fx": [
            "Wie viel sind 100 Dollar in Euro?",
            "Wie steht der Franken?",
            "Euro in Pfund?",
            "Wie ist der Dollarkurs?",
            "Was sind 50 Kronen in Euro?",
        ],
        "money.power_price": [
            "Wann ist Strom heute am billigsten?",
            "Was kostet Strom an der Börse?",
        ],
        "money.fuel": [
            "Was kostet E10 gerade?",
            "Wo tanke ich am billigsten?",
            "Wie teuer ist Diesel?",
        ],
        "water.level": ["Wie hoch steht die Lahn?", "Wasserstand Lahn?", "Steigt die Lahn?"],
        "water.flood": ["Gibt es Hochwasser?", "Ist was mit Hochwasser?"],
        "waste.next": [
            "Welche Tonne kommt morgen?",
            "Wann kommt die gelbe Tonne?",
            "Wann ist Sperrmüll?",
            "Wann wird die Papiertonne geleert?",
        ],
        "waste.week": ["Was wird diese Woche abgeholt?"],
        "football.last": ["Wie hat die Eintracht gespielt?"],
        "football.next": ["Wann spielt die Eintracht?"],
        "football.table": ["Auf welchem Platz steht die Eintracht?"],
        "news.headlines": ["Was gibt's Neues?", "Nachrichten?", "Was sind die Schlagzeilen?"],
        "notes.add": [
            "Schreib Milch auf die Einkaufsliste.",
            "Notiz: Reifen wechseln",
            "Setz Eier auf die Einkaufsliste",
        ],
        "notes.read": ["Was steht auf der Einkaufsliste?", "Lies meine Notizen vor"],
        "notes.clear": ["Lösch die Einkaufsliste."],
    }
)

# sentences no skill may answer: other topics, compound requests, near misses (SKILL-01, R23)
NEGATIVE: list[str] = [
    "Um wie viel Uhr fährt der Zug nach Frankfurt?",
    "Wann öffnet der Supermarkt?",
    "Um wie viel Uhr beginnt der Film?",
    "Ich hab keine Zeit",
    "Das Wetter ist mir egal",
    "Wie war das Wetter im Urlaub?",
    "Erzähl mir etwas über die Geschichte von Hessen und was dort im Mittelalter passiert ist",
    "Wer war der erste Bundeskanzler",
    "Was ist die Hauptstadt von Australien",
    "Wie viele Einwohner hat Frankfurt",
    "Schreib mir eine E-Mail an meinen Chef",
    "Mach das Licht an",
    "Ruf bitte meine Mutter an",
    "Wie funktioniert ein Dieselmotor",
    "Ich habe gestern Abend im Fernsehen einen Beitrag über Wetterphänomene in Kanada gesehen",
    "Wie lang ist die Lahn",
    "Wie teuer ist ein Auto",
    "Was kostet ein Flug nach Rom",
    "Spiel mir ein Lied",
    "Wie wird man Millionär",
    "Wie spät kommt der Bus",
    "Um wie viel Uhr geht die Sonne unter",
    "Wann ist die Sonne weg",
    "Das ist mir zu laut",
    "Wie heißt die Hauptstadt von Hessen",
    "Wie hoch ist der Feldberg",
    "Ich brauche eine neue Jacke zum Geburtstag",
    "Die Heizung ist kaputt",
    "Mein Fahrrad hat einen Platten",
    "Der Müll stinkt schon wieder",
    "Ich habe 100 Euro im Lotto gewonnen",
    "Wie viel kostet ein Liter Milch",
    "Was soll ich zum Abendessen kochen",
]

# conversations: the sentence only works with what was said before
FOLLOWUPS: list[dict] = [
    {"prior": ["Wie lange noch bis Weihnachten?"], "say": "Mehr Details", "skill": None},
    {"prior": ["Was kannst du?"], "say": "Mehr Details", "skill": "talk.details"},
    {"prior": ["Wie spät ist es?"], "say": "Woher weißt du das?", "skill": "talk.source"},
    {"prior": ["Stell einen Timer auf 5 Minuten"], "say": "Wie lange noch?", "skill": "timer.left"},
    {"prior": ["Wie spät ist es?"], "say": "Kannst du das wiederholen?", "skill": "talk.repeat"},
    {
        "prior": ["Wie spät ist es?"],
        "say": "Was habe ich dich gerade gefragt?",
        "skill": "talk.last_question",
    },
]


def main() -> None:
    lines = []
    for skill, phrases in POSITIVE.items():
        for phrase in phrases:
            lines.append({"say": phrase, "skill": skill})
    for phrase in NEGATIVE:
        lines.append({"say": phrase, "skill": None})
    lines.extend(FOLLOWUPS)
    target = (
        Path(__file__).resolve().parents[1] / "tests" / "moritz_agent" / "data" / "skills.de.jsonl"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8"
    )
    print(f"{len(lines)} Zeilen → {target}")


if __name__ == "__main__":
    main()
