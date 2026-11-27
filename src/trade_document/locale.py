"""Only document labels are translated. Business wording remains the reviewed source."""

STRINGS = {
    "Proforma Invoice": ("Proformarechnung", "Facture pro forma"),
    "Sample Proforma Invoice": (
        "Proformarechnung für Muster",
        "Facture pro forma pour échantillons",
    ),
    "Sample Order Sheet": ("Musterauftrag", "Commande d’échantillons"),
    "Seller": ("Verkäufer", "Vendeur"),
    "Buyer": ("Käufer", "Acheteur"),
    "Document no.": ("Belegnummer", "N° de document"),
    "Issue date": ("Ausstellungsdatum", "Date d’émission"),
    "Currency": ("Währung", "Devise"),
    "Customization": ("Anpassung", "Personnalisation"),
    "Sample policy": ("Musterregelung", "Conditions des échantillons"),
    "Credit toward bulk order": (
        "Gutschrift bei Großauftrag",
        "Avoir sur commande en volume",
    ),
    "Payment terms": ("Zahlungsbedingungen", "Conditions de paiement"),
    "Delivery terms": ("Lieferbedingungen", "Conditions de livraison"),
    "Freight payable by": ("Frachtzahler", "Fret à la charge de"),
    "Payment instructions": ("Zahlungsanweisung", "Instructions de paiement"),
    "Seller address": ("Anschrift Verkäufer", "Adresse vendeur"),
    "Buyer address": ("Anschrift Käufer", "Adresse acheteur"),
    "Ship to": ("Lieferadresse", "Adresse de livraison"),
    "PO reference": ("Bestellnummer", "Référence commande"),
    "Valid until": ("Gültig bis", "Valable jusqu’au"),
    "SKU": ("SKU", "SKU"),
    "Description / specification": (
        "Beschreibung / Spezifikation",
        "Description / spécification",
    ),
    "Quantity": ("Menge", "Quantité"),
    "Unit": ("Einheit", "Unité"),
    "Unit price": ("Einzelpreis", "Prix unitaire"),
    "Amount": ("Betrag", "Montant"),
    "Subtotal": ("Zwischensumme", "Sous-total"),
    "Sample fee": ("Mustergebühr", "Frais d’échantillon"),
    "Freight": ("Fracht", "Fret"),
    "Discount": ("Rabatt", "Remise"),
    "Total": ("Gesamt", "Total"),
    "Insurance": ("Versicherung", "Assurance"),
    "Tooling fee": ("Werkzeugkosten", "Frais d’outillage"),
    "Pending": ("Ausstehend", "À confirmer"),
    "Authorized signature": ("Freigabeunterschrift", "Signature autorisée"),
    "Page": ("Seite", "Page"),
    "DRAFT": ("ENTWURF", "BROUILLON"),
    "Revision": ("Fassung", "Révision"),
    "Acceptance criteria": ("Abnahmekriterien", "Critères de réception"),
    "Trade term": ("Handelsklausel", "Terme commercial"),
}


def label(order, key):
    if order.language == "en" or key not in STRINGS:
        return key
    return STRINGS[key][0 if order.language == "de" else 1]
