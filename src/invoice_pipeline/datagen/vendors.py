"""Pool of synthetic vendor profiles and product/service descriptions used to
generate varied sample invoices."""

from __future__ import annotations

VENDORS = [
    {
        "id": "acme_supplies",
        "name": "Acme Industrial Supplies",
        "address": ["4821 Foundry Rd", "Cleveland, OH 44113"],
        "currency": "USD",
        "tax_rate": 0.0725,
    },
    {
        "id": "brightline_consulting",
        "name": "Brightline Consulting Group",
        "address": ["220 Market St, Suite 900", "San Francisco, CA 94105"],
        "currency": "USD",
        "tax_rate": 0.0,
    },
    {
        "id": "northwind_traders",
        "name": "Northwind Traders Ltd.",
        "address": ["12 Elm Grove", "Manchester, M1 4BT, UK"],
        "currency": "GBP",
        "tax_rate": 0.20,
    },
    {
        "id": "cobalt_logistics",
        "name": "Cobalt Logistics & Freight",
        "address": ["900 Harbor Blvd", "Long Beach, CA 90802"],
        "currency": "USD",
        "tax_rate": 0.0875,
    },
    {
        "id": "pixel_forge_studio",
        "name": "Pixel Forge Studio",
        "address": ["77 Rue de Rivoli", "75004 Paris, France"],
        "currency": "EUR",
        "tax_rate": 0.20,
    },
    {
        "id": "granite_office_supply",
        "name": "Granite Office Supply Co.",
        "address": ["1500 Industrial Pkwy", "Austin, TX 78745"],
        "currency": "USD",
        "tax_rate": 0.0625,
    },
    {
        "id": "meridian_it_services",
        "name": "Meridian IT Services",
        "address": ["8 Raffles Quay, #21-01", "Singapore 048581"],
        "currency": "USD",
        "tax_rate": 0.0,
    },
    {
        "id": "copperfield_print",
        "name": "Copperfield Print & Design",
        "address": ["33 King St W", "Toronto, ON M5H 1A1, Canada"],
        "currency": "USD",
        "tax_rate": 0.13,
    },
    {
        "id": "vertex_hardware",
        "name": "Vertex Hardware Distribution",
        "address": ["6100 Commerce Dr", "Phoenix, AZ 85043"],
        "currency": "USD",
        "tax_rate": 0.081,
    },
    {
        "id": "solstice_marketing",
        "name": "Solstice Marketing Partners",
        "address": ["410 Peachtree St NE", "Atlanta, GA 30308"],
        "currency": "USD",
        "tax_rate": 0.0,
    },
]

CUSTOMERS = [
    {"name": "Harlow & Finch LLC", "address": ["200 Corporate Dr", "Columbus, OH 43215"]},
    {"name": "Ridgeline Manufacturing", "address": ["55 Industrial Way", "Denver, CO 80216"]},
    {"name": "BlueGate Retail Inc.", "address": ["901 Commerce Sq", "Charlotte, NC 28202"]},
    {"name": "Solaris Energy Partners", "address": ["18 Innovation Blvd", "San Diego, CA 92101"]},
    {"name": "Nimbus Software Co.", "address": ["500 2nd Ave, Fl 3", "Seattle, WA 98104"]},
    {"name": "Fairmont Hospitality Group", "address": ["77 Lakeshore Dr", "Chicago, IL 60601"]},
]

LINE_ITEM_POOL = [
    ("Consulting services - senior engineer", 150.00, "hr"),
    ("Consulting services - project manager", 125.00, "hr"),
    ("Widget assembly, model A-12", 4.25, "unit"),
    ("Widget assembly, model B-7", 6.75, "unit"),
    ("Freight & handling", 89.00, "flat"),
    ("Office chair, ergonomic", 210.00, "unit"),
    ("Standing desk, adjustable", 340.00, "unit"),
    ("Printer toner cartridge, black", 42.50, "unit"),
    ("Network switch, 24-port", 265.00, "unit"),
    ("Cloud hosting - monthly", 480.00, "month"),
    ("Software license - annual seat", 199.00, "seat"),
    ("Graphic design - logo package", 650.00, "flat"),
    ("Print run - business cards (500ct)", 38.00, "box"),
    ("Warehouse pallet storage", 22.00, "pallet"),
    ("Custom bracket, stainless steel", 11.40, "unit"),
    ("Marketing campaign management", 1200.00, "month"),
    ("IT support retainer", 800.00, "month"),
    ("Replacement HVAC filter", 14.75, "unit"),
    ("Safety goggles, bulk pack", 3.10, "unit"),
    ("On-site training session", 900.00, "session"),
]
