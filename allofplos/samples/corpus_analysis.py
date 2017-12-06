"""
This set of functions is for analyzing all the articles in the PLOS corpus. A Jupyter Notebook is provided with
examples of analysis. It can:
    * compare the articles indexed in Solr, PMC, and content-repo
    * spot-check individual JATS fields for irregularities
    * create summaries of articles by type, publication date, etc
    * generate lists of retracted or corrected articles
"""

import collections
import csv
import os
import progressbar
import random
import requests

from ..plos_regex import (validate_doi, corpusdir, newarticledir, full_doi_regex_match,
                          validate_url, currents_doi_filter)
from ..transformations import (filename_to_doi, doi_to_path, doi_to_url)
from ..plos_corpus import (listdir_nohidden, uncorrected_proofs_text_list,
                           download_updated_xml, get_all_solr_dois, download_check_and_move)
from ..article_class import Article

counter = collections.Counter
pmcdir = "pmc_articles"
max_invalid_files_to_print = 100
pmcdir = 'pmc_articles'


def validate_corpus(corpusdir=corpusdir):
    """
    For every local article file and DOI listed on Solr, validate file names, DOIs, URLs in terms of
    regular expressions.
    Stops checking as soon as encounters problem and prints it
    :return: boolean of whether corpus passed validity checks
    """
    # check DOIs
    plos_dois = get_all_plos_dois()
    plos_valid_dois = [doi for doi in plos_dois if validate_doi(doi)]
    if set(plos_dois) == set(plos_valid_dois):
        pass
    else:
        print("Invalid DOIs: {}".format(set(plos_dois) - set(plos_valid_dois)))
        return False

    # check urls
    plos_urls = [doi_to_url(doi) for doi in plos_valid_dois]
    plos_valid_urls = [url for url in plos_urls if validate_url(url)]
    if set(plos_urls) == set(plos_valid_urls) and len(plos_valid_urls) == len(plos_valid_dois):
        pass
    else:
        print("Invalid URLs: {}".format(set(plos_urls) - set(plos_valid_urls)))
        return False

    # check files and filenames
    plos_files = listdir_nohidden(corpusdir)
    if plos_files:
        plos_valid_filenames = [article for article in plos_files if validate_file(article)]
        if len(plos_valid_dois) == len(plos_valid_filenames):
            pass
        else:
            print("Invalid filenames: {}".format(set(plos_valid_dois) - set(plos_valid_filenames)))
            return False
        plos_valid_files = [article for article in plos_valid_filenames if os.path.isfile(article)]
        if set(plos_valid_filenames) == set(plos_valid_files):
            return True
        else:
            invalid_files = set(plos_valid_filenames) - set(plos_valid_files)
            if len(invalid_files) > max_invalid_files_to_print:
                print("Too many invalid files to print: {}".format(len(invalid_files)))
            else:
                print("Invalid files: {}".format(invalid_files))
            return False
    else:
        print("Corpus directory empty. Re-download by running create_local_plos_corpus()")
        return False

# These functions are for getting the article types of all PLOS articles.


def get_jats_article_type_list(article_list=None, directory=corpusdir):
    if article_list is None:
        article_list = listdir_nohidden(directory)

    jats_article_type_list = []

    for article_file in article_list:
        article = Article.from_filename(article_file, directory=directory)
        jats_article_type_list.append(article.type_)

    print(len(set(jats_article_type_list)), 'types of articles found.')
    article_types_structured = counter(jats_article_type_list).most_common()
    return article_types_structured


def get_plos_article_type_list(article_list=None, directory=corpusdir):

    if article_list is None:
        article_list = listdir_nohidden(directory)

    PLOS_article_type_list = []

    for article_file in article_list:
        article = Article.from_filename(article_file, directory=directory)
        PLOS_article_type_list.append(article.plostype)

    print(len(set(PLOS_article_type_list)), 'types of articles found.')
    PLOS_article_types_structured = counter(PLOS_article_type_list).most_common()
    return PLOS_article_types_structured


# Get tuples of article types mapped for all PLOS articles
def get_article_types_map(article_list=None, directory=corpusdir):
    if article_list is None:
        article_list = listdir_nohidden(directory)
    article_types_map = []
    max_value = len(article_list)
    bar = progressbar.ProgressBar(redirect_stdout=True, max_value=max_value)
    for i, article_file in enumerate(article_list):
        article = Article.from_filename(article_file)
        article.directory = directory
        types = [article.type_, article.plostype, article.dtd]
        types = tuple(types)
        article_types_map.append(types)
        bar.update(i+1)
    bar.finish()
    return article_types_map


# write article types map to .csv file
def article_types_map_to_csv(article_types_map):
    with open('articletypes.csv', 'w') as out:
        csv_out = csv.writer(out)
        csv_out.writerow(['type', 'count'])
        for row in article_types_map:
            csv_out.writerow(row)


# These functions are for getting retracted articles


def get_retracted_doi_list(article_list=None, directory=corpusdir):
    """
    Scans through articles in a directory to see if they are retraction notifications,
    scans articles that are that type to find DOIs of retracted articles
    :return: tuple of lists of DOIs for retractions articles, and retracted articles
    """
    retractions_doi_list = []
    retracted_doi_list = []
    if article_list is None:
        article_list = listdir_nohidden(directory)
    for art in article_list:
        article = Article.from_filename(art)
        article.directory = directory
        if article.type_ == 'retraction':
            retractions_doi_list.append(article.doi)
            # Look in those articles to find actual articles that are retracted
            retracted_doi_list.extend(article.related_dois)
            # check linked DOI for accuracy
            for doi in article.related_dois:
                if bool(full_doi_regex_match.search(doi)) is False:
                    print("{} has incorrect linked DOI field: '{}'".format(article_file, doi))
    print(len(retracted_doi_list), 'retracted articles found.')
    return retractions_doi_list, retracted_doi_list


def get_amended_article_list(article_list=None, directory=corpusdir):
    """
    Scans through articles in a directory to see if they are amendment notifications,
    scans articles that are that type to find DOI substrings of amended articles
    :param article: the filename for a single article
    :param directory: directory where the article file is, default is corpusdir
    :return: list of DOIs for articles issued a correction
    """
    amendments_article_list = []
    amended_article_list = []
    if article_list is None:
        article_list = listdir_nohidden(directory)

    # check for amendments article type
    for art in article_list:
        article = Article.from_filename(art)
        article.directory = directory
        if article.amendment:
            amendments_article_list.append(article.doi)
            # get the linked DOI of the amended article
            amended_article_list.extend(article.related_dois)
            # check linked DOI for accuracy
            for doi in article.related_dois:
                if bool(full_doi_regex_match.search(doi)) is False:
                    print(article.doi, "has incorrect linked DOI:", doi)
    print(len(amended_article_list), 'amended articles found.')
    return amendments_article_list, amended_article_list


# These functions are for checking for silent XML updates

def create_pubdate_dict(directory=corpusdir):
    """
    For articles in directory, create a dictionary mapping them to their pubdate.
    Used for truncating the revisiondate_sanity_check to more recent articles only
    :return: a dictionary mapping article files to datetime objects of their pubdates
    """
    articles = listdir_nohidden(directory)
    pubdates = {art: Article.from_filename(art).pubdate for art in articles}
    return pubdates


def revisiondate_sanity_check(article_list=None, tempdir=newarticledir, directory=corpusdir, truncated=True):
    """
    :param truncated: if True, restrict articles to only those with pubdates from the last year or two
    """
    list_provided = bool(article_list)
    if article_list is None and truncated is False:
        article_list = listdir_nohidden(directory)
    if article_list is None and truncated:
        pubdates = create_pubdate_dict(directory=directory)
        article_list = sorted(pubdates, key=pubdates.__getitem__, reverse=True)
        article_list = article_list[:30000]

    try:
        os.mkdir(tempdir)
    except FileExistsError:
        pass
    articles_different_list = []
    max_value = len(article_list)
    bar = progressbar.ProgressBar(redirect_stdout=True, max_value=max_value)
    for i, article_file in enumerate(article_list):
        updated = download_updated_xml(article_file=article_file)
        if updated:
            articles_different_list.append(article_file)
        if list_provided:
            article_list.remove(article_file)  # helps save time if need to restart process
        bar.update(i+1)
    bar.finish()
    print(len(article_list), "article checked for updates.")
    print(len(articles_different_list), "articles have updates.")
    return articles_different_list


# These functions are for getting & analyzing the PLOS Corpus from PMC


def article_doi_sanity_check(directory=corpusdir, article_list=None, source='solr'):
    """
    For every article in a directory, make sure that the DOI field is both valid and matches
    the file name, if applicable. Prints invalid DOIs that don't match regex.
    :return: list of articles where the filename does not match the linked DOI
    """
    messed_up_articles = []
    if article_list is None:
        if source == 'PMC':
            article_list = listdir_nohidden(pmcdir, extension='.nxml')
        elif source == 'solr':
            article_list = listdir_nohidden(corpusdir)
    doifile_dict = {get_article_doi(article_file=article_file): article_file for article_file in article_list}
    doi_list = list(doifile_dict.keys())
    # check for PLOS regular regex
    bad_doi_list = [doi for doi in full_doi_filter(doi_list) if doi is not False]
    # check for Currents regex if PMC
    if bad_doi_list:
        if directory == pmcdir or source == 'PMC':
            bad_doi_list = currents_doi_filter(bad_doi_list)
    for doi in bad_doi_list:
        print("{} has invalid DOI field: '{}'".format(doifile_dict[doi], doi))
    if directory == corpusdir or source == 'solr':
        messed_up_articles = [doifile_dict[doi] for doi in doi_list if filename_to_doi(doifile_dict[doi]) != doi]
        if len(messed_up_articles) == 0:
            print('All article file names match DOIs.')
        else:
            print(len(messed_up_articles), 'article files have DOI errors.')
        return messed_up_articles
    return bad_doi_list


def get_articles_by_doi_field(directory=pmcdir, article_list=None, check_new=True):
    doi_to_pmc = {}
    if directory == pmcdir and article_list is None:
        article_list = get_pmc_articles()
    elif article_list is None:
        article_list = listdir_nohidden(directory)
        if article_list == 0:
            article_list = listdir_nohidden(directory, extension='.nxml')

    if directory != pmcdir:
        for article in article_list:
            doi = get_article_doi(article_file=article)
            doi_to_pmc[doi] = article
    else:
        try:
            # read doi_to_pmc dict from csv
            with open(pmc_csv, 'r') as csv_file:
                reader = csv.reader(csv_file)
                next(reader, None)
                doi_to_pmc = dict(reader)

            scratch = False
            n = 0
            if check_new:
                for article in article_list:
                    if article not in doi_to_pmc.values():
                        doi = get_article_doi(article)
                        doi_to_pmc[doi] = os.path.basename(article).rstrip('.nxml').rstrip('.xml')
                        n = n + 1
                if n:
                    print(n, 'DOI/PMCID pairs added to dictionary.')

        except FileNotFoundError:
            print('Creating doi_to_pmc dictionary from scratch.')
            scratch = True
            n = 0
            file_list = listdir_nohidden(pmcdir, extension='.nxml')
            doi_to_pmc = {get_article_doi(pmc_file): os.path.basename(pmc_file).rstrip('.nxml') for pmc_file in file_list}
        # write doi_to_pmc dict to csv
        if scratch or n > 0:
            with open(pmc_csv, 'w') as f:
                writer = csv.writer(f)
                writer.writerow(['DOI', 'PMC ID'])
                for key, value in doi_to_pmc:
                    writer.writerow([key, value])
            print('DOI, PMC ID list exported to', pmc_csv)

    return doi_to_pmc


def check_solr_doi(doi):
    '''
    For an article doi, see if there's a record of it in Solr.
    '''
    solr_url = 'http://api.plos.org/search?q=*%3A*&fq=doc_type%3Afull&fl=id,&wt=json&indent=true&fq=id:%22{}%22'.format(doi)
    article_search = requests.get(solr_url).json()
    return bool(article_search['response']['numFound'])


def get_all_local_dois(corpusdir=corpusdir):
    local_dois = [filename_to_doi(art) for art in listdir_nohidden(corpusdir)]
    return local_dois


def get_all_plos_dois(local_articles=None, solr_articles=None):
    '''
    Collects lists of articles for local and solr, calculates the difference.
    Missing local downloads easily solved by re-running plos_corpus.py.
    Missing solr downloads require attention.
    :return: every DOI in PLOS corpus, across local and remote versions
    '''
    if solr_articles is None:
        solr_articles = get_all_solr_dois()
    if local_articles is None:
        local_articles = get_all_local_dois()
    missing_local_articles = set(solr_articles) - set(local_articles)
    if missing_local_articles:
        print('re-run plos_corpus.py to download latest {0} PLOS articles locally.'
              .format(len(missing_local_articles)))
    missing_solr_articles = set(local_articles) - set(solr_articles)
    plos_articles = set(solr_articles + local_articles)
    if missing_solr_articles:
        print('\033[1m' + 'Articles that needs to be re-indexed on Solr:')
        print('\033[0m' + '\n'.join(sorted(missing_solr_articles)))

    return plos_articles


def get_random_list_of_dois(directory=corpusdir, count=100):
    '''
    Gets a list of random DOIs. Tries first to construct from local files in
    corpusdir, otherwise tries Solr DOI list as backup.
    :param directory: defaults to searching corpusdir
    :param count: specify how many DOIs are to be returned
    :return: a list of random DOIs for analysis
    '''
    try:
        article_list = listdir_nohidden(directory)
        sample_file_list = random.sample(article_list, count)
        sample_doi_list = [filename_to_doi(file) for file in sample_file_list]
    except OSError:
        doi_list = get_all_solr_dois()
        sample_doi_list = random.sample(doi_list, count)
    return sample_doi_list


def get_article_metadata(article_file, size='small'):
    """
    For an individual article in the PLOS corpus, create a tuple of a set of metadata fields sbout that corpus.
    Make it small, medium, or large depending on number of fields desired.
    :param article_file: individual local PLOS XML article
    :param size: small, medium or large, aka how many fields to return for each article
    :return: tuple of metadata fields tuple, wrong_date_strings dict
    """
    article = Article.from_filename(article_file)
    doi = article.doi
    filename = os.path.basename(article.filename.rstrip('.xml'))
    title = article.title
    journal = article.journal
    jats_article_type = article.type_
    plos_article_type = article.plostype
    dtd_version = article.dtd
    dates = article.get_dates()
    (pubdate, collection, received, accepted) = ('', '', '', '')
    pubdate = article.pubdate
    counts = article.counts
    (fig_count, table_count, page_count) = ('', '', '')
    body_word_count = article.body_word_count
    related_articles = article.related_dois
    abstract = article.abstract
    try:
        collection = dates['collection']
    except KeyError:
        pass
    try:
        received = dates['received']
    except KeyError:
        pass
    try:
        accepted = dates['accepted']
    except KeyError:
        pass
    try:
        fig_count = counts['fig-count']
    except KeyError:
        pass
    try:
        table_count = counts['table-count']
    except KeyError:
        pass
    try:
        page_count = counts['page-count']
    except KeyError:
        pass
    metadata = [doi, filename, title, journal, jats_article_type, plos_article_type, dtd_version, pubdate, received,
                accepted, collection, fig_count, table_count, page_count, body_word_count, related_articles, abstract]
    metadata = tuple(metadata)
    if len(metadata) == 17:
        return metadata
    else:
        print('Error in {}: {} items'.format(article_file, len(metadata)))
        return False


def get_corpus_metadata(article_list=None):
    """
    Run get_article_metadata() on a list of files, by default every file in corpusdir
    Includes a progress bar
    :param article_list: list of articles to run it on
    :return: list of tuples for each article; list of dicts for wrong date orders
    """
    if article_list is None:
        article_list = listdir_nohidden(corpusdir)
    max_value = len(article_list)
    bar = progressbar.ProgressBar(redirect_stdout=True, max_value=max_value)
    corpus_metadata = []
    for i, article_file in enumerate(article_list):
        metadata = get_article_metadata(article_file)
        corpus_metadata.append(metadata)
        bar.update(i+1)
    bar.finish()
    return corpus_metadata


def corpus_metadata_to_csv(corpus_metadata=None,
                           article_list=None,
                           wrong_dates=None,
                           csv_file='allofplos_metadata.csv'):
    """
    Convert list of tuples from get_article_metadata to csv
    :param corpus_metadata: the list of tuples, defaults to creating from corpusdir
    :return: None
    """
    if corpus_metadata is None:
        corpus_metadata, wrong_dates = get_corpus_metadata(article_list)
    # write main metadata csv file
    with open(csv_file, 'w') as out:
        csv_out = csv.writer(out)
        csv_out.writerow(['doi', 'filename', 'title', 'journal', 'jats_article_type', 'plos_article_type',
                          'dtd_version', 'pubdate', 'received', 'accepted', 'collection', 'fig_count', 'table_count',
                          'page_count', 'body_word_count', 'related_article', 'abstract'])
        for row in corpus_metadata:
            csv_out.writerow(row)
    # write wrong dates csv file, with longest dict providing the keys
    if wrong_dates:
        keys = max(wrong_dates, key=len).keys()
        with open('wrong_dates.csv', 'w') as out:
            dict_writer = csv.DictWriter(out, keys)
            dict_writer.writeheader()
            dict_writer.writerows(wrong_dates)


def read_corpus_metadata_from_csv(csv_file='allofplos_metadata.csv'):
    """
    reads in a csv of data, excluding the header row
    :param csv_file: csv file of data, defaults to 'allofplos_metadata.csv'
    :return: list of tuples of article metadata
    """
    with open(csv_file, 'r') as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)
        corpus_metadata = [tuple(line) for line in reader]
    return corpus_metadata


def update_corpus_metadata_csv(csv_file='allofplos_metadata.csv', comparison_dois=None):
    """
    Incrementally update the metadata of PLOS articles in the csv file
    :param csv_file: csv file of data, defaults to 'allofplos_metadata.csv'
    :comparison_dois: list of DOIs to check whether their metadats is included
    return updated corpus metadata
    """
    # Step 1: get metadata and DOI list from existing csv file
    try:
        corpus_metadata = read_corpus_metadata_from_csv(csv_file)
        csv_doi_list = [row[0] for row in corpus_metadata]
    except FileNotFoundError:
        corpus_metadata = []
        csv_doi_list = []
    # Step 2: compare DOI list with master list
    if comparison_dois is None:
        comparison_dois = get_all_solr_dois()
    dois_needed_list = list(set(comparison_dois) - set(csv_doi_list))
    # Step 3: compare to local file list
    local_doi_list = [filename_to_doi(article_file) for article_file in listdir_nohidden(corpusdir)]
    files_needed_list = list(set(dois_needed_list) - set(local_doi_list))
    if files_needed_list:
        print('Local corpus must be updated before .csv metadata can be updated.\nUpdating local corpus now')
        download_check_and_move(files_needed_list,
                                uncorrected_proofs_text_list,
                                tempdir=newarticledir,
                                destination=corpusdir)

    # Step 4: append new data to existing list
    new_corpus_metadata, wrong_dates = get_corpus_metadata(article_list=dois_needed_list)
    corpus_metadata.extend(new_corpus_metadata)
    # Step 5: write new dataset to .csv
    corpus_metadata_to_csv(corpus_metadata=corpus_metadata, csv_file='allofplos_metadata_updated.csv')
    return corpus_metadata
