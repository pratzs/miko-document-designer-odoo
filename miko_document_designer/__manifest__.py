# -*- coding: utf-8 -*-
{
    'name': 'Document Designer: Invoice PDF (Miko)',
    'version': '19.0.1.0.0',
    'summary': 'Design every printed document in one screen: fonts, table style, watermark, letterhead',
    'description': """
One screen for the whole look of your printed documents.

Odoo's own layout screen stops at logo, colours and font. This adds the rest:
table density, striped rows, numbered lines, product pictures on the lines, a
watermark, a letterhead PDF printed behind every page, terms and conditions
appended as a last page, the total written out in words, and a bank details
block.

It applies to every document you print - quotations, invoices, purchase orders,
delivery slips - and it installs on its own. No other app is pulled in, and
nothing is required beyond the Odoo you already run.

Everything Odoo already owns is written straight back to the company, not
shadowed, so your existing reports stay correct and uninstalling this module
leaves your branding exactly as you set it.

Rules let one customer, or one document type, print differently from the rest.
""",
    'author': 'Tripster Developers',
    'website': 'https://tripsterdevelopers.com/odoo/',
    'category': 'Accounting',
    'license': 'OPL-1',
    # Nothing but the web client, on purpose. An invoice designer that pulls in
    # Invoicing, Sales and Purchase to reach their report templates installs
    # three apps a buyer did not ask for; doing the same work after the report
    # is rendered costs one dependency-free pass and reaches documents those
    # modules do not own.
    'depends': ['web'],
    'data': [
        'security/miko_document_security.xml',
        'security/ir.model.access.csv',
        'views/miko_report_layouts.xml',
        'views/miko_document_designer_views.xml',
    ],
    'price': 199.00,
    'currency': 'USD',
    # The animated cover first: it is the image at the top of the app page and in
    # search results. The still is the same document at the last frame, generated
    # from the same source by make_banner_gif.py so the two cannot disagree.
    'images': ['images/banner.gif', 'images/banner.png'],
    'application': True,
    'installable': True,
    'support': 'support@tripsterdevelopers.com',
}
