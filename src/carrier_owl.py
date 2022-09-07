from webdriver_manager.firefox import GeckoDriverManager
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import NoSuchElementException
import os
import time
import yaml
import datetime
import slackweb
import argparse
import textwrap
from bs4 import BeautifulSoup
import warnings
import urllib.parse
from dataclasses import dataclass
import arxiv
import requests
# setting
warnings.filterwarnings('ignore')

@dataclass
class Result:
    url: str
    title: str
    title_trans: str
    abstract: str
    abstract_trans: str
    words: list
    score: float = 0.0


def calc_score(abst: str, keywords: dict) -> (float, list):
    sum_score = 0.0
    hit_kwd_list = []

    for word in keywords.keys():
        score = keywords[word]
        if word.lower() in abst.lower():
            sum_score += score
            hit_kwd_list.append(word)
    return sum_score, hit_kwd_list


def search_keyword(
        articles: list, keywords: dict, score_threshold: float
        ) -> list:
    results = []
    
    # ヘッドレスモードでブラウザを起動
    options = Options()
    options.add_argument('--headless')

    # ブラウザーを起動
    driver = webdriver.Firefox(executable_path=GeckoDriverManager().install(), options=options)
    
    for article in articles:
        url = article['arxiv_url']
        title = article['title']
        abstract = article['summary']
        score, hit_keywords = calc_score(abstract, keywords)
        if (score != 0) and (score >= score_threshold):
            title = title.replace('-\n', '').replace('\n', ' ').replace('/', ',')
            title_trans = get_translated_text('ja', 'en', title, driver)
            abstract = abstract.replace('-\n', '').replace('\n', ' ').replace('/', ',')
            abstract_trans = get_translated_text('ja', 'en', abstract, driver)
            abstract =  textwrap.wrap(abstract, 80)  # 80行で改行
            abstract = '\n'.join(abstract)
            abstract_trans = textwrap.wrap(abstract_trans, 40)  # 40行で改行
            abstract_trans = '\n'.join(abstract_trans)
            result = Result(
                        url=url,
                        title=title,
                        title_trans=title_trans,
                        abstract=abstract,
                        abstract_trans=abstract_trans,
                        score=score,
                        words=hit_keywords,
            )
            results.append(result)
    
    # ブラウザ停止
    driver.quit()
    return results


def send2app(text: str, slack_id: str, line_token: str) -> None:
    # slack
    if slack_id is not None:
        slack = slackweb.Slack(url=slack_id)
        slack.notify(text=text)

    # line
    if line_token is not None:
        line_notify_api = 'https://notify-api.line.me/api/notify'
        headers = {'Authorization': f'Bearer {line_token}'}
        data = {'message': f'message: {text}'}
        requests.post(line_notify_api, headers=headers, data=data)


def notify(results: list, slack_id: str, line_token: str) -> None:
    # 通知
    star = '*'*80
    today = datetime.date.today()
    n_articles = len(results)
    text = f'{star}\n \t \t {today}\tnum of articles = {n_articles}\n{star}'
    send2app(text, slack_id, line_token)
    # descending
    for result in sorted(results, reverse=True, key=lambda x: x.score):
        url = result.url
        title = result.title
        title_trans = result.title_trans
        abstract = result.abstract
        abstract_trans = result.abstract_trans
        word = result.words
        score = result.score

        text = f'\n score: `{score}`'\
               f'\n hit keywords: `{word}`'\
               f'\n url: {url}'\
               f'\n title:    {title}'\
               f'\n タイトル:    {title_trans}'\
               f'\n abstract:'\
               f'\n \t {abstract}'\
               f'\n \t {abstract_trans}'\
               f'\n {star}'

        send2app(text, slack_id, line_token)


def get_translated_text(from_lang: str, to_lang: str, from_text: str, driver) -> str:
    '''
    https://qiita.com/fujino-fpu/items/e94d4ff9e7a5784b2987
    '''

    sleep_time = 1

    # urlencode
    from_text = urllib.parse.quote(from_text)

    # url作成
    url = 'https://www.deepl.com/translator#' \
        + from_lang + '/' + to_lang + '/' + from_text

    driver.get(url)
    print(driver.page_source)
    driver.implicitly_wait(10)  # 見つからないときは、10秒まで待つ

    for i in range(30):
        # 指定時間待つ
        time.sleep(sleep_time)
        html = driver.page_source
        to_text = get_text_from_page_source(html)

        if to_text:
            break
    return to_text


def get_text_from_page_source(html: str) -> str:
    soup = BeautifulSoup(html, features='lxml')
    
#     search_class = "lmt__inner_textarea_container"
#     search_class = "lmt__translations_as_text"
#     search_class = "lmt__translations_as_text__text_btn"
    search_class = "lmt__textarea"
    
    print(soup.find(class_=search_class))
    target_elem = soup.find(class_=search_class)
    text = target_elem.text
    return text


def get_config() -> dict:
    file_abs_path = os.path.abspath(__file__)
    file_dir = os.path.dirname(file_abs_path)
    config_path = f'{file_dir}/../config.yaml'
    with open(config_path, 'r') as yml:
        config = yaml.load(yml)
    return config


def main():
    # debug用
    parser = argparse.ArgumentParser()
    parser.add_argument('--slack_id', default=None)
    parser.add_argument('--line_token', default=None)
    args = parser.parse_args()

    config = get_config()
    subject = config['subject']
    keywords = config['keywords']
    score_threshold = float(config['score_threshold'])

    day_before_yesterday = datetime.datetime.today() - datetime.timedelta(days=5)
    day_before_yesterday_str = day_before_yesterday.strftime('%Y%m%d')
    # datetime format YYYYMMDDHHMMSS
    arxiv_query = f'({subject}) AND ' \
                  f'submittedDate:' \
                  f'[{day_before_yesterday_str}000000 TO {day_before_yesterday_str}235959]'
    articles = arxiv.query(query=arxiv_query,
                           max_results=1000,
                           sort_by='submittedDate',
                           iterative=False)
    results = search_keyword(articles, keywords, score_threshold)

    slack_id = os.getenv("SLACK_ID") or args.slack_id
    line_token = os.getenv("LINE_TOKEN") or args.line_token
    notify(results, slack_id, line_token)


if __name__ == "__main__":
    main()
