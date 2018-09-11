#!/usr/bin/env python

"""
Copyright(c)2008 Internet Archive. Software license AGPL version 3.

This file is part of bookserver.

    bookserver is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    bookserver is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with bookserver.  If not, see <http://www.gnu.org/licenses/>.
    
    The bookserver source is hosted at http://github.com/internetarchive/bookserver/
    
"""

from Catalog import Catalog
from Entry import Entry
from OpenSearch import OpenSearch
from Navigation import Navigation
from Link import Link

import copy
import lxml.etree as ET
import re

import sys
sys.path.append("/petabox/sw/lib/python")
import feedparser #for _parse_date()
import datetime
import string
import opensearch

class CatalogRenderer:
    """Base class for catalog renderers"""

    def __init__(self):
        pass

    def toString(self):
        return ''

    def prettyPrintET(self, etNode):
        return ET.tostring(etNode, pretty_print=True)

class CatalogToAtom(CatalogRenderer):

    #some xml namespace constants
    #___________________________________________________________________________
    xmlns_atom    = 'http://www.w3.org/2005/Atom'
    xmlns_dcterms = 'http://purl.org/dc/terms/'
    xmlns_opds    = 'http://opds-spec.org/'

    atom          = "{%s}" % xmlns_atom
    dcterms       = "{%s}" % xmlns_dcterms
    opdsNS        = "{%s}" % xmlns_opds

    nsmap = {
        None     : xmlns_atom,
        'dcterms': xmlns_dcterms,
        'opds'   : xmlns_opds
    }

    fileExtMap = {
        'pdf'  : 'application/pdf',
        'epub' : 'application/epub+zip',
        'mobi' : 'application/x-mobipocket-ebook'
    }

    ebookTypes = ('application/pdf',
                  'application/epub+zip',
                  'application/x-mobipocket-ebook'
    )

    # createTextElement()
    #___________________________________________________________________________
    def createTextElement(self, parent, name, value):
        element = ET.SubElement(parent, name)
        element.text = value
        return element

    # createRelLink()
    #___________________________________________________________________________
    def createRelLink(self, parent, rel, urlroot, relurl, title=None, type='application/atom+xml'):
        absurl = urlroot + relurl
        element = ET.SubElement(parent, 'link')
        element.attrib['rel'] = rel
        element.attrib['type'] = type
        element.attrib['href'] = absurl
        if title:
            element.attrib['title'] = title

    # createOpdsRoot()
    #___________________________________________________________________________
    def createOpdsRoot(self, c):
        ### TODO: add updated element and uuid element
        opds = ET.Element(CatalogToAtom.atom + "feed", nsmap=CatalogToAtom.nsmap)
        opds.base = c._url

        self.createTextElement(opds, 'title', c._title)
        self.createTextElement(opds, 'id', c._urn)
        self.createTextElement(opds, 'updated', c._datestr)
        self.createRelLink(opds, 'self', c._url, '')

        author = ET.SubElement(opds, 'author')
        self.createTextElement(author, 'name', c._author)
        self.createTextElement(author, 'uri', c._authorUri)

        if c._crawlableUrl:
            self.createRelLink(opds, 'http://opds-spec.org/crawlable', c._crawlableUrl, '', 'Crawlable feed')

        return opds

    # createOpdsLink()
    #___________________________________________________________________________
    def createOpdsLink(self, entry, link):
        element = ET.SubElement(entry, 'link')
        element.attrib['href'] = link.get('url')
        element.attrib['type'] = link.get('type')
        if link.get('title'):
            element.attrib['title'] = link.get('title')

        if link.get('rel'):
            element.attrib['rel'] = link.get('rel')

        if link.get('price'):
            price = self.createTextElement(element, CatalogToAtom.opdsNS+'price', link.get('price'))
            price.attrib['currencycode'] = link.get('currencycode')

        if link.get('formats'):
            for format in link.get('formats'):
                self.createTextElement(element, CatalogToAtom.dcterms+'hasFormat', format)

        availability = link.get('availability')
        if availability:
            sub = ET.SubElement(element, self.opdsNS+'availability')
            sub.attrib['status'] = availability
            if availability == 'unavailable':
               sub = ET.SubElement(element, self.opdsNS+'unavailable')
               sub.attrib['date'] = link.get('date')

        holds = link.get('holds')
        if holds:
            sub = ET.SubElement(element, self.opdsNS+'holds')
            sub.attrib['total'] = str(holds)

        copies = link.get('copies')
        if copies:
            sub = ET.SubElement(element, self.opdsNS+'copies')
            sub.attrib['total'] = '1' # currently archive.org only makes one copy available at a time
            sub.attrib['available'] = str(copies)

        # Indirect Acquisition for borrowable books:
        # <opds:indirectAcquisition type="application/vnd.adobe.adept+xml">
        #   <opds:indirectAcquisition type="application/epub+zip"/>
        # </opds:indirectAcquisition>
        if availability:
            epub_ac = ET.SubElement(element, self.opdsNS+'indirectAcquisition')
            epub_ac.attrib['type'] = 'application/vnd.adobe.adept+xml'
            sub = ET.SubElement(epub_ac, self.opdsNS+'indirectAcquisition')
            sub.attrib['type'] = 'application/epub+zip'
            pdf_ac = copy.copy(epub_ac)
            pdf_ac[0].attrib['type'] = 'application/pdf'
            element.append(pdf_ac)

    # createOpdsEntry()
    #___________________________________________________________________________
    def createOpdsEntry(self, opds, obj, links, fabricateContentElement):
        entry = ET.SubElement(opds, 'entry')
        self.createTextElement(entry, 'title', obj['title'])

        # FIXME: July 2018 TEMPORARY WORKAROUND for issue with Aldiko iOS client 1.1.6
        # Where id/urn was being used to form url links under https scheme.
        # Apparently fixed after v1.1.6, but we want to demo current progress.
        if 'identifier' in obj:
            # standard id=urn for book entries
            #urn = 'urn:x-internet-archive:bookserver:' + nss
            self.createTextElement(entry, 'id', obj['urn'])
        else:
            # id=url for catalog navigation entries
            self.createTextElement(entry, 'id', links[0].get('url'))

        self.createTextElement(entry, 'updated', obj['updated'])
        downloadLinks = []
        for link in links:
            self.createOpdsLink(entry, link)
            if link.get('type') in CatalogToAtom.ebookTypes:
                downloadLinks.append(link)

        if 'date' in obj:
            # TODO: Unify publication date, pick a spec
            # Displayed by Aldiko
            element = self.createTextElement(entry, self.dcterms+'issued', obj['date'][0:4])
            # Displayed by SimplyE, but with too much precision (1 January YYYY), won't display YYYY only
            element = self.createTextElement(entry, 'published', obj['date'])

        if 'authors' in obj:
            for author in obj['authors']:
                element = ET.SubElement(entry, 'author')
                self.createTextElement(element, 'name', author)

        if 'subjects' in obj:
            for subject in obj['subjects']:
                element = ET.SubElement(entry, 'category')
                element.attrib['term'] = subject
                element.attrib['label'] = subject

        if 'publisher' in obj:
            element = self.createTextElement(entry, self.dcterms+'publisher', obj['publisher'])

        if 'languages' in obj:
            for language in obj['languages']:
                element = self.createTextElement(entry, self.dcterms+'language', language)

        if 'description' in obj:
            element = self.createTextElement(entry, 'summary', ' '.join(obj['description']))
            element.attrib['type'] = 'html'

        if 'content' in obj:
            self.createTextElement(entry, 'content', obj['content'])
        elif 'description' in obj:
            # TODO: Not sure we need fabricateContentElement, the following line simply copies the description
            # to the location where Aldiko will display it.
            contentText = ' '.join(obj['description'])

        elif fabricateContentElement:
            ### fabricate an atom:content element if asked to
            ### FireFox won't show the content element if it contains nested html elements
            # TODO: Remove this section?
            contentText=''

            if 'contributors' in obj:
                contentText += '<b>Book contributor: </b>' + ', '.join(obj['contributors']) + '<br/>'

            if 'downloadsPerMonth' in obj:
                contentText += str(obj['downloadsPerMonth']) + ' downloads in the last month' + '<br/>'

            if 'provider' in obj:
                contentText += '<b>Provider: </b>' + obj['provider'] + '<br/>'

            element = self.createTextElement(entry, 'content', contentText)
            element.attrib['type'] = 'html'

    def createAuthentication(self, opds, auth_url):
        self.createRelLink(opds, 'http://opds-spec.org/auth/document', auth_url, '', type='application/vnd.opds.authentication.v1.0+json')

    # createOpenSearchDescription()
    #___________________________________________________________________________
    def createOpenSearchDescription(self, opds, opensearch):
        self.createRelLink(opds, 'search', opensearch.osddUrl, '', None, type='application/opensearchdescription+xml')

    # createNavLinks()
    #___________________________________________________________________________
    def createNavLinks(self, opds, nav):
        if nav.prevLink:
            self.createRelLink(opds, 'prev', '', nav.prevLink, nav.prevTitle)

        if nav.nextLink:
            self.createRelLink(opds, 'next', '', nav.nextLink, nav.nextTitle)

    # __init__()
    #___________________________________________________________________________
    def __init__(self, c, fabricateContentElement=False):
        CatalogRenderer.__init__(self)
        self.opds = self.createOpdsRoot(c)

        if c._opensearch:
            self.createOpenSearchDescription(self.opds, c._opensearch)

        if c._navigation:
            self.createNavLinks(self.opds, c._navigation)

        if c._authentication:
            self.createAuthentication(self.opds, c._authentication)

        for e in c._entries:
            self.createOpdsEntry(self.opds, e._entry, e._links, fabricateContentElement)
            
        
    # toString()
    #___________________________________________________________________________
    def toString(self):
        return self.prettyPrintET(self.opds)

    # toElementTree()
    #___________________________________________________________________________
    def toElementTree(self):
        return self.opds


class CatalogToHtml(CatalogRenderer):
    """
    The HTML page is organised thus:
        PageHeader
        Navigation
        Search
        CatalogHeader
        EntryList
        PageFooter

        >>> h = CatalogToHtml(testCatalog)
        >>> # print(h.toString())
    """

    entryDisplayKeys = [
        'authors',
        'date',
        'publisher',
        'provider',
        'formats',
        'contributors',
        'languages',
        'downloadsPerMonth',
        'summary',
    ]

    entryDisplayTitles = {
        'authors': ('Author', 'Authors'),
        'contributors': ('Contributor', 'Contributors'),
        'date': ('Published', 'Published'),
        'downloadsPerMonth': ('Recent downloads', 'Recent downloads'),
        'formats': ('Format', 'Formats'),
        'languages': ('Language', 'Languages'),
        'provider': ('Provider', 'Provider'),
        'publisher': ( 'Publisher', 'Publisher'),
        'summary': ('Summary', 'Summary'),
        'title': ('Title', 'Title')
    }

    entryLinkTitles = {
        'application/pdf': 'PDF',
        'application/epub': 'ePub',
        'application/epub+zip': 'ePub',
        'application/x-mobipocket-ebook': 'Mobi',
        'text/html': 'Website',
    }

    def __init__(self, catalog, device = None, query = None, provider = None):
        CatalogRenderer.__init__(self)
        self.device = device
        self.query = query
        self.provider = provider
        self.processCatalog(catalog)

    def processCatalog(self, catalog):
        html = self.createHtml(catalog)
        html.append(self.createHead(catalog))
        body = self.createBody(catalog)
        html.append(body)
        body.append(self.createHeader(catalog))
        body.append(self.createSearch(catalog._opensearch, query = self.query))
        body.append(self.createCatalogHeader(catalog))
        body.append(self.createNavigation(catalog._navigation))
        body.append(self.createEntryList(catalog._entries))
        body.append(self.createNavigation(catalog._navigation))
        body.append(self.createFooter(catalog))

        self.html = html
        return self

    def createHtml(self, catalog):
        return ET.Element('html')

    def createHead(self, catalog):
        # $$$ updated
        # $$$ atom link

        head = ET.Element('head')
        titleElement = ET.SubElement(head, 'title')
        titleElement.text = catalog._title
        head.append(self.createStyleSheet('/static/catalog.css'))

        return head

    def createStyleSheet(self, url):
        """
        Returns a <link> element for the CSS stylesheet at given URL

        >>> l = testToHtml.createStyleSheet('/static/catalog.css')
        >>> ET.tostring(l)
        '<link href="/static/catalog.css" type="text/css" rel="stylesheet"/>'
        """

        # TODO add ?v={version}
        return ET.Element('link', {
            'rel':'stylesheet',
            'type':'text/css', 
            'href':url
        })

    def createBody(self, catalog):
        return ET.Element('body')

    def createHeader(self, catalog):
        div = ET.Element( 'div', {'class':'opds-header'} )
        div.text = 'Catalog Header'
        return div

    def createNavigation(self, navigation):
        """
        >>> start    = 5
        >>> numFound = 100
        >>> numRows  = 10
        >>> urlBase  = '/alpha/a/'
        >>> nav = Navigation.initWithBaseUrl(start, numRows, numFound, urlBase)
        >>> div = testToHtml.createNavigation(nav)
        >>> print ET.tostring(div)
        <div class="opds-navigation"><a href="/alpha/a/4.html" class="opds-navigation-anchor" rel="prev" title="Prev results">Prev results</a><a href="/alpha/a/6.html" class="opds-navigation-anchor" rel="next" title="Next results">Next results</a></div>
        """

        div = ET.Element( 'div', {'class':'opds-navigation'} )
        if not navigation:
            # No navigation provided, return empty div
            return div

        nextLink, nextTitle = navigation.nextLink, navigation.nextTitle
        prevLink, prevTitle = navigation.prevLink, navigation.prevTitle

        if (prevLink):
            prevA = self.createNavigationAnchor('prev', navigation.prevLink, navigation.prevTitle)
            div.append(prevA)
        else:
            # $$$ no further results, append appropriate element
            pass

        if (nextLink):
            nextA = self.createNavigationAnchor('next', navigation.nextLink, navigation.nextTitle)
            div.append(nextA)
        else:
            # $$$ no next results, append appropriate element
            pass

        return div

    def createNavigationAnchor(self, rel, url, title = None):
        """
        >>> a = testToHtml.createNavigationAnchor('next', 'a/1', 'Next results')
        >>> print ET.tostring(a)
        <a href="a/1.html" class="opds-navigation-anchor" rel="next" title="Next results">Next results</a>
        >>> a = testToHtml.createNavigationAnchor('prev', 'a/0.xml', 'Previous')
        >>> print ET.tostring(a)
        <a href="a/0.html" class="opds-navigation-anchor" rel="prev" title="Previous">Previous</a>
        """

        # Munge URL
        if url.endswith('.xml'):
            url = url[:-4]
        if not url.endswith('.html'):
            url += '.html'

        attribs = {'class':'opds-navigation-anchor',
            'rel': rel,
            'href': url}
        if title is not None:
            attribs['title'] = title    
        a = ET.Element('a', attribs)

        if title is not None:
            a.text = title
        return a

    def createSearch(self, opensearchObj, query = None):
        div = ET.Element( 'div', {'class':'opds-search'} )

        # load opensearch
        osUrl = opensearchObj.osddUrl
        desc = opensearch.Description(osUrl)
        url = desc.get_url_by_type('application/atom+xml')
        if url is None:
            c = ET.Comment()
            c.text = " Could not load OpenSearch description from %s " % osUrl
            div.append(c)
        else:
            template = url.template

            # XXX URL is currently hardcoded
            form = ET.SubElement(div, 'form', {'class':'opds-search-form', 'action':'/bookserver/catalog/search', 'method':'get' } )

            # ET.SubElement(form, 'input', {'class':'opds-search-template', 'type':'hidden', 'name':'t', 'value': template } )

            termsLabel = ET.SubElement(form, 'label', {'for':'opds-search-terms'} )
            termsLabel.text = desc.shortname
            ET.SubElement(form, 'br')

            searchAttribs = {'class':'opds-search-terms',
                'type':'text',
                'name':'q', 
                'id':'opds-search-terms',
                'size':'40',
            }

            if query:
                searchAttribs['value'] = query
            terms = ET.SubElement(form, 'input', searchAttribs )

            submit = ET.SubElement(form, 'input', {'class':'opds-search-submit', 'name':'submit', 'type':'submit', 'value':'Search'} )

            # $$$ expand to other devices
            if self.device and self.device.name == 'Kindle':
                deviceSubmit = ET.SubElement(form, 'input', {'class':'opds-search-submit', 'name':'device', 'type':'submit', 'value':'Search for Kindle' } )
            if self.provider:
                providerSubmit = ET.SubElement(form, 'input', {'class':'opds-search-submit', 'name':'provider', 'type':'submit', 'value':'Search %s' % self.provider} ) # $$$ use pretty name

        # XXX finish implementation
        return div

    def createCatalogHeader(self, catalog):
        div = ET.Element( 'div', {'class':'opds-catalog-header'} )
        title = ET.SubElement(div, 'h1', {'class':'opds-catalog-header-title'} )
        title.text = catalog._title # XXX
        return div

    def createEntry(self, entry):
        """
        >>> e = testToHtml.createEntry(testEntry)
        >>> print ET.tostring(e, pretty_print=True)
        <p class="opds-entry">
          <h2 class="opds-entry-title">test item</h2>
          <span class="opds-entry-item"><em class="opds-entry-key">Published:</em> <span class="opds-entry-value">1977</span><br/></span>
          <span class="opds-entry-item"><em class="opds-entry-key">Summary:</em> <span class="opds-entry-value">&lt;p&gt;Fantastic book.&lt;/p&gt;</span><br/></span>
          <div class="opds-entry-links">
            <span class="opds-entry-item"><em class="opds-entry-key">Buy:</em> <a href="http://archive.org/download/itemid.pdf" class="opds-entry-link">PDF</a></span>
          </div>
        </p>
        """

        e = ET.Element('p', { 'class':'opds-entry'} )

        elem = e        
        # Look for link to catalog, and if so, make the title of this entry a link
        catalogLink = self.findCatalogLink(entry._links)
        if catalogLink:
            entry._links.remove(catalogLink)
            a = ET.SubElement(e, 'a', { 'class':'opds-entry-title', 'href':catalogLink.get('url') } )
            elem = a

        title = ET.SubElement(elem, 'h2', {'class':'opds-entry-title'} )
        title.text = entry.get('title')

        for key in self.entryDisplayKeys:
            value = entry.get(key)
            if value:
                displayTitle, displayValue = self.formatEntryValue(key, value)

                entryItem = ET.SubElement(e, 'span', {'class':'opds-entry-item'} )
                itemName = ET.SubElement(entryItem, 'em', {'class':'opds-entry-key'} )
                itemName.text = displayTitle + ':'
                itemName.tail = ' '
                itemValue = ET.SubElement(entryItem, 'span', {'class': 'opds-entry-value' } )
                itemValue.text = unicode(displayValue)
                ET.SubElement(entryItem, 'br')

        if entry._links:
            e.append(self.createEntryLinks(entry._links))

        # TODO sort for display order
        # for key in Entry.valid_keys.keys():
        #    formattedEntryKey = self.createEntryKey(key, entry.get(key))
        #    if (formattedEntryKey):
        #        e.append( formattedEntryKey )
        return e

    def formatEntryValue(self, key, value):
        if type(value) == type([]):
            if len(value) == 1:
                displayTitle = self.entryDisplayTitles[key][0]
                displayValue = value[0]

            else:
                # Multiple items
                displayTitle = self.entryDisplayTitles[key][1]
                displayValue = ', '.join(value)
        else:
            # Single item
            displayTitle = self.entryDisplayTitles[key][0]
            displayValue = value
            if 'date' == key:
                displayValue = displayValue[:4]

        return (displayTitle, displayValue)

    def createEntryLinks(self, links):
        """
        >>> pdf = Link(url = 'http://a.o/item.pdf', type='application/pdf', rel='http://opds-spec.org/acquisition')
        >>> epub = Link(url = 'http://a.o/item.epub', type='application/epub+zip', rel='http://opds-spec.org/acquisition')
        >>> links = [pdf, epub]
        >>> e = testToHtml.createEntryLinks(links)
        >>> print ET.tostring(e, pretty_print=True)
        <div class="opds-entry-links">
          <span class="opds-entry-item"><em class="opds-entry-key">Free:</em> <a href="http://a.o/item.pdf" class="opds-entry-link">PDF</a>, <a href="http://a.o/item.epub" class="opds-entry-link">ePub</a></span>
        </div>
        """

        free = []
        buy = []
        lend = []
        subscribe = []
        sample = []
        opds = [] # XXX munge link for HTML proxy - make entry title the link
        html = []

        d = ET.Element('div', {'class':'opds-entry-links'} )

        for link in links:
            try:
                rel = link.get('rel')
                type = link.get('type')
            except KeyError:
                # no relation
                continue

            if rel == Link.acquisition:
                free.append(link)
            elif rel == Link.buying:
                buy.append(link)
            elif rel == Link.lending:
                lend.append(link)
            elif rel == Link.subscription:
                subscribe.append(link)
            elif rel == Link.sample:
                sample.append(link)
            elif type == Link.opds:
                opds.append(link)
            elif type == Link.html:
                html.append(link)
            # XXX output uncaught links

        linkTuples = [(free, 'Free:'), (buy, 'Buy:'), (subscribe, 'Subscribe:'), (sample, 'Sample:'), (opds, 'Catalog:'), (html, 'HTML:')]

        for (linkList, listTitle) in linkTuples:
            if len(linkList) > 0:
                s = ET.Element('span', { 'class':'opds-entry-item' } )
                title = ET.SubElement(s, 'em', {'class':'opds-entry-key'} )
                title.text = listTitle
                title.tail = ' '

                linkElems = [self.createEntryLink(aLink) for aLink in linkList]
                for linkElem in linkElems:
                    s.append(linkElem)
                    if linkElem != linkElems[-1]:
                        linkElem.tail = ', '

                d.append(s)

        return d

    def createEntryLink(self, link):
        """
        >>> l = Link(url = 'http://foo.com/bar.pdf', type='application/pdf')
        >>> e = testToHtml.createEntryLink(l)
        >>> print ET.tostring(e)
        <a href="http://foo.com/bar.pdf" class="opds-entry-link">PDF</a>

        >>> l = Link(url = '/blah.epub', type='application/epub')
        >>> e = testToHtml.createEntryLink(l)
        >>> print ET.tostring(e)
        <a href="/blah.epub" class="opds-entry-link">ePub</a>
        """

        if self.device:
            link = self.device.formatLink(link)

        if self.entryLinkTitles.has_key(link.get('type')):
            title = self.entryLinkTitles[link.get('type')]
        else:
            title = link.get('url')

        attribs = {'class':'opds-entry-link',
            'href' : link.get('url')
        }

        #try:
        #    attribs['type'] = link.get('type')
        #except:
        #    pass

        a = ET.Element('a', attribs)
        a.text = title
        return a

    def createEntryKey(self, key, value):
        # $$$ legacy

        if not value:
            # empty
            return None

        # XXX handle lists, pretty format key, order keys
        e = ET.Element('span', { 'class': 'opds-entry' })
        keyName = ET.SubElement(e, 'em', {'class':'opds-entry-key'})
        keyName.text = unicode(key, 'utf-8') + ':'
        keyName.tail = ' '
        keyValue = ET.SubElement(e, 'span', { 'class': 'opds-entry-value opds-entry-%s' % key })
        keyValue.text = unicode(value)
        ET.SubElement(e, 'br')
        return e

    def createEntryList(self, entries):
        list = ET.Element( 'ul', {'class':'opds-entry-list'} )
        for entry in entries:
            item = ET.SubElement(list, 'li', {'class':'opds-entry-list-item'} )
            item.append(self.createEntry(entry))
            list.append(item)
        return list

    def createFooter(self, catalog):
        div = ET.Element('div', {'class':'opds-footer'} )
        div.text = 'Page Footer Div' # XXX
        return div

    @classmethod
    def findCatalogLink(cls, links):
        # $$$ should be moved elsewhere -- refactor
        """
        >>> links = [Link( **{ 'type': Link.acquisition, 'url': 'buynow' }), Link( **{'type': Link.opds, 'url': '/providers'}) ]
        >>> catalogLink = CatalogToHtml.findCatalogLink(links)
        >>> print catalogLink.get('url')
        /providers
        """

        if links:
            for link in links:
                try:
                    linkType = link.get('type')
                except KeyError:
                    continue

                if Link.opds == linkType:
                    return link
        return None

    def toString(self):
        return self.prettyPrintET(self.html)

#_______________________________________________________________________________
        
class CatalogToSolr(CatalogRenderer):
    '''
    Creates xml that can be sent to a Solr POST command
    '''

    def isEbook(self, entry):
        for link in entry.getLinks():            
            if 'application/pdf' == link.get('type'):
                return True
            elif 'application/epub+zip' == link.get('type'):
                return True
            elif 'application/x-mobipocket-ebook' == link.get('type'):
                return True
            elif ('buynow' == link.get('rel')) and ('text/html' == link.get('type')):
                #special case for O'Reilly Stanza feeds
                return True

        return False

    def addField(self, element, name, data, catchAll=False):
        field = ET.SubElement(element, "field")
        field.set('name', name)
        field.text=data

        if catchAll:
            #copy this field into the solr catchAll field "text"
            field = ET.SubElement(element, "field")
            field.set('name', 'text')
            field.text=data        

    def addList(self, element, name, data, catchAll=False):
        for scalar in data:
            self.addField(element, name, scalar, catchAll)

    def makeSolrDate(self, datestr):
        """
        Solr is very particular about the date format it can handle
        """
        d = feedparser._parse_date(datestr)
        date = datetime.datetime(d.tm_year, d.tm_mon, d.tm_mday, d.tm_hour, d.tm_min, d.tm_sec)
        return date.isoformat()+'Z'

    def addEntry(self, entry):
        """
        Add each ebook as a Solr document
        """

        if not self.isEbook(entry):
            return

        p = re.compile('\w', re.UNICODE)
        m = p.search(entry.get('title'))
        if not m:
            print "not indexing book with non-alphanum title: " + entry.get('title')
            return

        if entry.get('rights'):
            #Special case for Feedbooks
            if "This work is available for countries where copyright is Life+70." == entry.get('rights'):
                print "not indexing Life+70 book: " + entry.get('title')
                return

        doc = ET.SubElement(self.solr, "doc")
        self.addField(doc, 'urn', entry.get('urn'))
        self.addField(doc, 'provider', self.provider)
        self.addField(doc, 'title', entry.get('title'), True)
        self.addField(doc, 'rights', entry.get('rights'), True)
        self.addField(doc, 'publisher', entry.get('publisher'), True)

        self.addList(doc, 'creator', entry.get('authors'), True)
        self.addList(doc, 'language', entry.get('languages'))
        self.addList(doc, 'subject', entry.get('subjects'), True)

        self.addField(doc, 'updated', self.makeSolrDate(entry.get('updated')))

        if entry.get('summary'):
            if not 'No description available.' == entry.get('summary'): #Special case for Feedbooks
                self.addField(doc, 'summary',     entry.get('summary'), True)

        if entry.get('date'):
            try:
                date = datetime.datetime(int(entry.get('date')), 1, 1)
                self.addField(doc, 'date', date.isoformat()+'Z')
            except ValueError:
                print """Can't make datetime from """ + entry.get('date')

        if entry.get('title'):
            try:
                self.addField(doc, 'firstTitle',  entry.get('title').lstrip(string.punctuation+string.whitespace)[0].upper())
            except IndexError:
                print """Can't make firstTitle from """ + entry.get('title')
            self.addField(doc, 'titleSorter', entry.get('title').lstrip(string.punctuation+string.whitespace).lower())

        #TODO: deal with creatorSorter, languageSorter

        price = None            #TODO: support multiple prices for different formats
        currencyCode = None
        for link in entry.getLinks():            
            if 'application/pdf' == link.get('type'):
                self.addField(doc, 'format', 'pdf')
                self.addField(doc, 'link', link.get('url'))
                if link.get('price'):
                    price = link.get('price')
                    currencyCode = link.get('currencycode')
            elif 'application/epub+zip' == link.get('type'):
                self.addField(doc, 'format', 'epub')
                self.addField(doc, 'link', link.get('url'))
                if link.get('price'):
                    price = link.get('price')
                    currencyCode = link.get('currencycode')
            elif 'application/x-mobipocket-ebook' == link.get('type'):
                self.addField(doc, 'format', 'mobi')
                self.addField(doc, 'link', link.get('url'))
                if link.get('price'):
                    price = link.get('price')
                    currencyCode = link.get('currencycode')
            elif ('buynow' == link.get('rel')) and ('text/html' == link.get('type')):
                #special case for O'Reilly Stanza feeds
                self.addField(doc, 'format', 'shoppingcart')
                self.addField(doc, 'link', link.get('url'))
                if link.get('price'):
                    price = link.get('price')
                    currencyCode = link.get('currencycode')

        if price:
            if not currencyCode:
                currencyCode = 'USD'
        else:
            price = '0.00'
            currencyCode = 'USD'

        self.addField(doc, 'price', price)
        self.addField(doc, 'currencyCode', currencyCode)
        ### old version of lxml on the cluster does not have lxml.html package
        #if 'OReilly' == self.provider: 
        #    content = html.fragment_fromstring(entry.get('content'))
        #    price = content.xpath("//span[@class='price']")[0]
        #    self.addField(doc, 'price', price.text.lstrip('$'))
        #elif ('IA' == self.provider) or ('Feedbooks' == self.provider):
        #    self.addField(doc, 'price', '0.00')


    def createRoot(self):
        return ET.Element("add")

    def __init__(self, catalog, provider):
        CatalogRenderer.__init__(self)
        self.provider = provider

        self.solr = self.createRoot()

        for entry in catalog.getEntries():
            self.addEntry(entry)

    def toString(self):
        return self.prettyPrintET(self.solr)

#_______________________________________________________________________________

def testmod():
    import doctest
    global testEntry, testCatalog, testToHtml, testArchiveToHtml

    urn = 'urn:x-internet-archive:bookserver:catalog'
    testCatalog = Catalog(title='Internet Archive OPDS', urn=urn)
    testLink    = Link(url  = 'http://archive.org/download/itemid.pdf',
                       type = 'application/pdf', rel='http://opds-spec.org/acquisition/buying')
    catalogLink = Link(url = '/providers/IA', type = Link.opds)
    testEntry = Entry({'urn'  : 'x-internet-archive:item:itemid',
                        'title'   : u'test item',
                        'updated' : '2009-01-01T00:00:00Z',
                        'date': '1977-06-17T00:00:55Z',
                        'summary': '<p>Fantastic book.</p>',
                        },
                        links=[testLink])

    start    = 0
    numFound = 2
    numRows  = 1
    urlBase  = '/alpha/a/'
    testNavigation = Navigation.initWithBaseUrl(start, numRows, numFound, urlBase)
    testCatalog.addNavigation(testNavigation)

    osDescription = 'http://bookserver.archive.org/catalog/opensearch.xml'
    testSearch = OpenSearch(osDescription)
    testCatalog.addOpenSearch(testSearch)

    testCatalog.addEntry(testEntry)
    testToHtml = CatalogToHtml(testCatalog)

    testArchiveToHtml = ArchiveCatalogToHtml(testCatalog)

    doctest.testmod()

if __name__ == "__main__":
    testmod()

