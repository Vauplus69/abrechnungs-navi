# Einwilligung und Google-Ads-Anfragen

Stand 06.11.2026. Ausschließlich Abrechnungs-Navi, eigenes Ads-Konto unter marketfuxx@gmail.com. Keine Kampagnenaktivierung durch diesen Einbau.

Die selbst gehostete Einwilligungsabfrage bietet gleichrangig Ablehnen, Einstellungen und Akzeptieren. Notwendige Speicherung der Auswahl unter an_consent_v1: 180 Tage, Version 1 und Zeitstempel. Optionales Ads-Feld standardmäßig aus. Einwilligung lässt sich jederzeit mit Cookie-Einstellungen ändern. Kein JavaScript bedeutet kein Google-Tag. Blockierte Browser-Speicherung darf die Anfrage nicht verhindern; ohne beständige Auswahl kann erneut gefragt werden.

Grundlegender Einwilligungsmodus: Ohne gültige Zustimmung keine Google-Skripte und keine Cookieless-Pings. Nur Startseite und danke.html laden bei Zustimmung das Google-Tag. analytics_storage und ad_personalization bleiben denied; ad_storage/ad_user_data nur nach Zustimmung granted. Keine erweiterten Conversions und keine Übergabe von Formularinhalten. Öffentliches Tag und Label in ads-config.js sind keine Zugangsdaten. enabled:false schaltet das Laden ab, auch wenn früher zugestimmt wurde.

Vor dem Laden werden unbekannte Query-Parameter aus der öffentlichen Seitenadresse entfernt; nur syntaktisch begrenzte gclid, gbraid und wbraid bleiben. Bekannte Abschnittsanker bleiben bedienbar. Referenzadresse wird auf die Herkunftsdomain gekürzt. Der geschützte Upload und die Verwaltung enthalten kein Tag und behalten ihre bisherige Content-Security-Policy. Google-Freigaben der CSP gelten ausschließlich für Start- und Dankeseite. Keine pauschalen Wildcard-Domains oder unsafe-eval ergänzt.

Eine Conversion entsteht ausschließlich nach erfolgreicher serverseitiger Speicherung einer Anfrage mit mitgeteilter Ads-Zustimmung. Dann wird ein zufälliger, zwei Minuten gültiger Einmalnachweis als Secure/HttpOnly/SameSite-Strict-Cookie an_conversion für /tracking/receipt gesetzt. Der Nachweis enthält keine Anfrage-ID oder Formularangaben. Die Anfrage dokumentiert die Version und serverseitige Zeit der mitgeteilten Zustimmung innerhalb der normalen Anfrageaufbewahrung. Die Dankeseite verbraucht den Nachweis nach Zustimmung einmalig. Das Ergebnis ist eine weitere zufällige Transaktionskennung ohne Personenbezug im Kennungsinhalt. Direkter Seitenaufruf, Honeypot, ungültiges Formular, Ablehnung oder Wiederholung erzeugen kein Conversion-Ereignis. Mailzustellung ist davon getrennt und muss gesondert überwacht werden. Eine angenommene Anfrage ist kein Auftrag und kein Umsatz; übermittelter Wert 0 EUR. Google-Zählweise auf Eine, Standardwert auf 0 EUR gesetzt.

Ein Neustart des Anwendungsdienstes oder ein Ablauf des Einmalnachweises kann diese einzelne Messung verlieren. Das beeinträchtigt die Anfrageannahme nicht. Adblocker, verweigerte Einwilligung und Browserregeln führen ebenfalls zu Messlücken. Keine vollständige Erfassung sämtlicher Kundenkontakte behaupten.

Widerruf speichert Ablehnung, löscht erreichbare _gcl_/_gac_-Werbespeicher und führt bei bereits geladenem Tag sofort zu einem Neuladen ohne Tag. Änderungen aus anderen Tabs werden berücksichtigt; ablaufende Zustimmung wird auch in offen gebliebenen Tabs kontrolliert. Drittanbieter-Cookies auf Google-Domains und bereits übermittelte Daten lassen sich dadurch nicht rückwirkend löschen.

Prüfung: 44 Python-Tests, 32 JavaScript-Prüfungen; zusätzlich bestehende Preisrechnerprüfungen. Browserablauf lokal mit synthetischen Angaben, simuliertem Google-Tag und abgeschaltetem Mailversand prüfen. Keine synthetischen Kundenanfragen in Produktion erzeugen. Ein erfolgreicher lokaler Test ist keine von Google bestätigte Ads-Zuordnung. Google-Tag-Diagnose kann nach Implementierung bis zu 48 Stunden nachlaufen.

Quellen:
- https://developers.google.com/tag-platform/security/guides/consent?hl=de
- https://developers.google.com/tag-platform/security/guides/csp
- https://support.google.com/google-ads/answer/7548399?hl=de
- https://business.safety.google/adscookies/
- https://policies.google.com/privacy/frameworks?hl=de
