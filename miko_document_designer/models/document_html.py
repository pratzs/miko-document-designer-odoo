# -*- coding: utf-8 -*-
"""DOM work on the rendered document, done without depending on anything.

Product pictures on the lines, the total in words and the bank block all used to
mean inheriting `account.report_invoice_document`, `sale.report_saleorder_document`
and `purchase.report_purchaseorder_document` - which means depending on
Invoicing, Sales and Purchase, so a buyer who wanted a nicer invoice would have
had three extra apps installed for them.

Doing it here instead, on the HTML the report engine has already produced, costs
one lxml pass and works on every document any module prints, including ones that
did not exist when this was written. The anchors it uses - `table.o_main_table`,
`div#total`, and the section/note/subtotal row classes - are core's own and are
identical on 16, 17, 18 and 19.

Every function here refuses rather than guesses. Putting the wrong product
picture next to a line, on a document that goes to a customer, is worse than not
printing pictures at all.
"""
from lxml import etree, html as lxml_html

from .design import LINE_IMAGE_CLASS, NON_PRODUCT_ROW_CLASSES

MAIN_TABLE = (
    ".//table[contains(concat(' ', normalize-space(@class), ' '),"
    " ' o_main_table ')]"
)


def _classes(node):
    return set((node.get('class') or '').split())


def _normalised(text):
    return ' '.join((text or '').split()).lower()


def find_article_nodes(root):
    return root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]")


def find_line_rows(article):
    """The rows of the line table that stand for a product line.

    Section headers, notes and running subtotals are excluded by the same class
    names the stylesheet excludes, so a numbered line and a pictured line always
    mean the same set of rows.
    """
    tables = article.xpath(MAIN_TABLE)
    if not tables:
        return []
    rows = tables[0].xpath('./tbody/tr')
    skip = set(NON_PRODUCT_ROW_CLASSES)
    return [row for row in rows if not (_classes(row) & skip)]


def inject_line_images(article, items, size=48):
    """Put a picture in the first cell of each product row.

    `items` is a list of (line label, image data URI) in the order the document
    renders them. The pairing is checked before anything is written: the number
    of rows has to match the number of lines exactly, and each row's text has to
    contain the label of the line it is being paired with. If either check
    fails, nothing is written at all and the document prints as it would have.

    Returns True when pictures were added.
    """
    rows = find_line_rows(article)
    if not rows or len(rows) != len(items):
        return False

    targets = []
    for row, (label, uri) in zip(rows, items):
        cells = row.xpath('./td')
        if not cells:
            return False
        needle = _normalised((label or '').split('\n')[0])[:40]
        if needle and needle not in _normalised(' '.join(row.itertext())):
            # The row we are about to caption is not the line we think it is.
            return False
        targets.append((cells[0], uri))

    added = False
    for cell, uri in targets:
        if not uri:
            continue
        image = etree.Element('img')
        image.set('class', LINE_IMAGE_CLASS)
        image.set('src', uri)
        image.set('style', 'max-height: %dpx; max-width: %dpx;' % (size, size))
        # The cell's own leading text belongs to the cell, not to a child, so it
        # has to be handed to the image as a tail or inserting at position 0
        # would silently reorder the description.
        image.tail = cell.text
        cell.text = None
        cell.insert(0, image)
        added = True
    return added


def inject_after_totals(article, fragment_html):
    """Place a block immediately after the document's totals.

    `div#total` is core's own id and is in the invoice, the quotation and the
    purchase order on every series. A document without one gets the block at the
    end of the article instead, which is where a reader would look for it.
    """
    if not fragment_html:
        return False
    fragment = lxml_html.fragment_fromstring(fragment_html)
    totals = article.xpath(".//*[@id='total']")
    if totals:
        totals[-1].addnext(fragment)
    else:
        article.append(fragment)
    return True


def build_words_block(label, words):
    """"Total in words" as it is printed. Escaped here so callers cannot forget."""
    if not words:
        return ''
    # The gap is a margin, not a space character. A trailing space inside the
    # <strong> is collapsed away, and a non-breaking space between the two
    # inline elements measures a few pixels at report sizes - both printed the
    # label glued to the amount on a real page.
    return ('<p class="mb-1"><strong style="margin-right: 6px;">%s</strong>'
            '<span>%s</span></p>' % (_escape(label), _escape(words)))


def build_bank_block(title, rows):
    """`rows` is a list of (bank name, account number)."""
    printable = [(name or '', number or '') for name, number in rows if number]
    if not printable:
        return ''
    body = ''.join(
        '<div>%s%s</div>' % (('%s - ' % _escape(name)) if name else '',
                             _escape(number))
        for name, number in printable)
    return ('<div class="mt-2 p-2" style="border: 1px solid #dee2e6;'
            ' max-width: 60%%; display: inline-block;">'
            '<strong>%s</strong>%s</div>' % (_escape(title), body))


def build_totals_block(*fragments):
    kept = [fragment for fragment in fragments if fragment]
    if not kept:
        return ''
    return '<div class="miko-totals-extra">%s</div>' % ''.join(kept)


def _escape(value):
    return (str(value or '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def serialise(root):
    # Bytes, because that is what core hands `_prepare_html` and what it parses
    # again straight afterwards. Handing back a unicode string would work today
    # and depends on lxml's tolerance rather than on the contract.
    return lxml_html.tostring(root, encoding='utf-8')


def parse(html):
    return lxml_html.fromstring(
        html, parser=lxml_html.HTMLParser(encoding='utf-8'))
