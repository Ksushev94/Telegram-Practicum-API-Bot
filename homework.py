import logging
import os
import requests
import sys
import time

from dotenv import load_dotenv
from telebot import TeleBot


load_dotenv()


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def check_tokens():
    """Проверяет доступность переменных окружения, необходимых для работы бота.
    Если отсутствует хотя бы одна переменная окружения —
    продолжать работу бота нет смысла.
    """
    missing_tokens = []
    if not PRACTICUM_TOKEN:
        missing_tokens.append('PRACTICUM_TOKEN')
    if not TELEGRAM_TOKEN:
        missing_tokens.append('TELEGRAM_TOKEN')
    if not TELEGRAM_CHAT_ID:
        missing_tokens.append('TELEGRAM_CHAT_ID')
    if missing_tokens:
        error_message = (
            'Отсутствуют обязательные переменные окружения: '
            f'{", ".join(missing_tokens)}. Программа остановлена.'
        )
        logger.critical(error_message)
        sys.exit(error_message)
    else:
        logger.debug('Все необходимые переменные окружения доступны.')


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат.
    Принимает на вход два параметра: экземпляр класса TeleBot и строку
    с текстом сообщения.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug(f'Сообщение успешно отправлено в Telegram: "{message}"')
    except Exception as error:
        error_message = f'Ошибка при отправке сообщения в Telegram: {error}'
        logger.error(error_message)
        raise


def get_api_answer(timestamp):
    """Делает запрос к API-сервису Практикум Домашка.
    Принимает временную метку (timestamp) для получения последних обновлений.
    В случае успешного запроса возвращает ответ API, приведенный из JSON
    к типам данных Python.
    """
    payload = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        if response.status_code != 200:
            error_message = (
                f'Получен неожиданный статус кода: {response.status_code}'
            )
            logger.error(error_message, exc_info=True)
            raise requests.exceptions.HTTPError(error_message)
        return response.json()
    except requests.exceptions.RequestException as error:
        error_message = f'Сбой при запросе к эндпоинту {ENDPOINT}: {error}'
        logger.error(error_message, exc_info=True)
        raise Exception(f'Ошибка API: {error_message}') from error
    except ValueError as error:
        error_message = f'Невалидный JSON в ответе API: {error}'
        logger.error(error_message)
        raise
    except Exception as error:
        error_message = f'Непредвиденная ошибка: {error}'
        logger.error(error_message)
        raise


def check_response(response):
    """Проверяет ответ API на соответствие документации.
    В качестве параметра функция получает ответ API,
    приведённый к типам данных Python.
    """
    if not isinstance(response, dict):
        error_message = 'Ответ API не является словарем'
        logger.error(error_message)
        raise TypeError(error_message)
    if 'homeworks' not in response:
        error_message = 'В ответе API отсутствует ключ "homeworks"'
        logger.error(error_message)
        raise KeyError(error_message)
    if not isinstance(response['homeworks'], list):
        error_message = 'Значение ключа "homeworks" не является списком'
        logger.error(error_message)
        raise TypeError(error_message)
    if 'current_date' not in response:
        error_message = 'В ответе API отсутствует ключ "current_date".'
        logger.error(error_message)
        raise KeyError(error_message)
    homeworks = response['homeworks']
    if not homeworks:
        logger.debug('В ответе API отсутствуют новые статусы домашней работы.')
    return homeworks


def parse_status(homework):
    """Получает статус работы.
    Извлекает из информации о конкретной домашней работе
    статус этой работы.
    """
    if not isinstance(homework, dict):
        error_message = 'Элемент домашней работы не является словарем.'
        logger.error(error_message)
        raise TypeError(error_message)
    if 'homework_name' not in homework:
        error_message = 'Отсутствует ключ "homework_name" в "homework".'
        logger.error(error_message)
        raise KeyError(error_message)
    if 'status' not in homework:
        error_message = 'Отсутствует ключ "status" в "homework".'
        logger.error(error_message)
        raise KeyError(error_message)
    homework_name = homework['homework_name']
    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        error_message = f'Неизвестный статус домашней работы: "{status}".'
        logger.error(error_message)
        raise ValueError(error_message)
    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    last_error_message = None
    check_tokens()
    bot = TeleBot(token=TELEGRAM_TOKEN)
    logger.info('Бот успешно инициализирован.')
    timestamp = int(time.time())
    logger.info('Бот начал работу.')
    while True:
        try:
            logger.info(f'Запрашиваем API с timestamp: {timestamp}')
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                logger.info(
                    f'Обнаружено {len(homeworks)} обновлений статусов '
                    'домашних работ.'
                )
                for homework in homeworks:
                    message_text = parse_status(homework)
                    send_message(bot, message_text)
            else:
                logger.debug('Нет новых статусов домашних работ.')
            timestamp = response.get('current_date', int(time.time()))
            if last_error_message:
                last_error_message = None
        except Exception as error:
            current_error_message = f'Сбой в работе программы: {error}'
            logger.error(current_error_message, exc_info=True)
            if current_error_message != last_error_message:
                try:
                    send_message(bot, current_error_message)
                    last_error_message = current_error_message
                except Exception as error_2:
                    logger.error(
                        f'Не удалось отправить сообщение об ошибке в Telegram:'
                        f'{error_2}'
                    )
        finally:
            logger.info(
                f'Ожидание {RETRY_PERIOD} секунд перед следующим запросом.'
            )
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
