from threading import Thread

import time

from bestbuy_wrapper import BestBuy
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import re
from flask import Flask, jsonify, request
from difflib import SequenceMatcher
from queue import Queue

app = Flask(__name__)


def compare_phones_emag(name, storage, product):
    product_string = product.manufacturer + ' ' + product.name
    if product_string.endswith('GB'):
        product_string = ' '.join(product_string.split(' ')[:-1])

    return SequenceMatcher(a=name.lower(), b=product_string.lower()).ratio() > 0.85


def compare_phones_cel(name, storage, product):
    product_string = product.manufacturer + ' ' + product.name
    if product_string.endswith('GB'):
        name += ' ' + storage

    # print(name, ' /// ', product_string)
    return name.lower() == product_string.lower()


queue = Queue()
final_list = []


def worker_thread():
    while True:
        item = queue.get()
        if len(final_list) >= 4 or item is None:
            break
        pj = make_product_json(item)
        if len(pj['store_urls']):
            final_list.append(pj)


class Emag:
    phone_pattern = re.compile('^Telefon mobil (.+?)(?:, (Dual SIM))?(?:, ([0-9]+GB))(?:, (3G|4G))?, (.+)$',
                               flags=re.IGNORECASE)

    @classmethod
    def get_store_object(cls, product):
        html = requests.get('https://www.emag.ro/search/' + quote_plus(product.name)).content
        soup = BeautifulSoup(html, 'html.parser')

        products = soup.find_all(class_='card-item js-product-data')
        for product_html in products:
            title = product_html.get('data-name')
            price = product_html.find(class_='product-new-price').text[0:-6]
            store_url = product_html.find(class_='product-title').get('href')
            image_url = product_html.find('img').get('src')

            if not cls.phone_pattern.match(title):
                continue

            phone_name, dual_sim, storage, network, color = cls.phone_pattern.match(title).groups()

            print('Comparing {} with {}'.format(phone_name, product.name))
            if compare_phones_emag(phone_name, storage, product):
                print(phone_name)
                return {'store': 'emag', 'price': price, 'store_url': store_url, 'image_url': image_url}
            return None


class Cel:
    phone_pattern = re.compile('^Telefon mobil (.+?)(?: (Dual SIM))?(?: ([0-9]+GB))(?: (3G|4G))? (.+)$',
                               flags=re.IGNORECASE)

    @classmethod
    def get_store_object(cls, product):
        print('http://www.cel.ro/cauta/' + quote_plus(product.name))
        html = requests.get('http://www.cel.ro/cauta/' + quote_plus(product.name)).content
        soup = BeautifulSoup(html, 'html.parser')

        products = soup.find_all(class_='productListingWrapper')
        for product_html in products:
            title = product_html.find(itemprop='name').text
            price = product_html.find(itemprop='price').text
            store_url = product_html.find(class_='productListing-data-b product_link product_name').get('href')
            image_url = product_html.find('img').get('src')

            if not cls.phone_pattern.match(title):
                continue

            phone_name, dual_sim, storage, network, color = cls.phone_pattern.match(title).groups()
            if compare_phones_cel(phone_name, storage, product):
                return {'store': 'cel', 'price': price, 'store_url': store_url, 'image_url': image_url}
            return None


def make_product_json(product):
    ret = {'name': '{} {}'.format(product.manufacturer, product.name), 'store_urls': []}

    emag = Emag.get_store_object(product)
    if emag:
        ret['store_urls'].append(emag)

    return ret


@app.route('/products', methods=['POST'])
def post():
    best_buy = BestBuy('MDhGMmNQnNCka8uLv5VKMWQD')

    args = request.json

    q = 'details.name=Phone Style&details.value=Smartphone&customerReviewCount>10&customerTopRated=true'

    if args['sim'] == 'yes':
        q += '&details.value=Dual SIM'

    products = best_buy.get_products(q)

    for prod in products:
        if filter_product(prod, args['size'], args['camera'], args['selfie'], args['battery'], args['ram'],
                          args['price']):
            queue.put(prod)

    for _ in range(8):
        queue.put(None)

    threads = []
    for _ in range(8):
        t = Thread(target=worker_thread)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return jsonify(final_list)


def filter_product(p, size, back, front, battery, ram, price):
    if not ((p.screen_size <= 6 and size == 'small') or (p.screen_size >= 5 and size == 'big')):
        return False

    if not (back == 'low' or (back == 'meh' and p.back_camera >= 5) or (back == 'high' and p.back_camera >= 8)):
        return False

    if not (front == 'no' or (front == 'sometimes' and p.front_camera >= 5) or (
                    front == 'yes' and p.front_camera >= 7)):
        return False

    if not (battery == 'no' or (battery == 'yes' and p.battery >= 20)):
        return False

    if not (ram == 'no' or (ram == 'yes' and p.ram >= 3)):
        return False

    if not (price == '2000' or (price == '500' and p.price * 4 <= 800) or (
                    price == '1000' and p.price * 4 <= 1700) or (
                    price == '1500' and p.price * 4 <= 2500)):
        return False

    return True


if __name__ == '__main__':
    app.run()

    # best_buy = BestBuy('NB0Cj7ExAegRczGVuGH38jHW')
    # products = best_buy.get_products('details.name=Phone Style&details.value=Smartphone&search=iphone&search=xs')

    # products_json = list(map(make_product_json, list(products)))
    # for p_json in [pj for pj in products_json if pj['store_urls']]:
    #     print(p_json)
