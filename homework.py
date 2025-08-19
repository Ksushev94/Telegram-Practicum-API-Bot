import http
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
import telebot.apihelper
from dotenv import load_dotenv
from telebot import TeleBot


load_dotenv()


PRACTICUM_TOKEN: Optional[str] = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN: Optional[str] = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID: Optional[str] = os.getenv('TELEGRAM_CHAT_ID')
RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


class APIError(Exception):
    """Исключение для ошибок, связанных с API Практикума."""

    pass


class ResponseValidationError(Exception):
    """Исключение для ошибок валидации структуры ответа API."""

    pass


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def check_tokens() -> List[str]:
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
    return missing_tokens


def send_message(bot: TeleBot, message: str) -> None:
    """Отправляет сообщение в Telegram-чат.

    Принимает на вход два параметра: экземпляр класса TeleBot и строку
    с текстом сообщения.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except (
        telebot.apihelper.ApiException,
        requests.exceptions.RequestException
    ) as error:
        error_message = f'Ошибка при отправке сообщения в Telegram: {error}'
        logger.error(error_message)
        raise
    else:
        logger.debug(f'Сообщение успешно отправлено в Telegram: "{message}"')


def get_api_answer(timestamp: int) -> Dict[str, Any]:
    """Делает запрос к API-сервису Практикум Домашка.

    Принимает временную метку (timestamp) для получения последних обновлений.
    В случае успешного запроса возвращает ответ API, приведенный из JSON
    к типам данных Python.
    """
    payload = {'from_date': timestamp}
    logger.info(f'Начинаем запрос к API {ENDPOINT} с параметрами: {payload}')
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
    except requests.exceptions.RequestException as error:
        raise APIError(
            f'Сбой при запросе к эндпоинту {ENDPOINT}: {error}'
        ) from error
    if response.status_code != http.HTTPStatus.OK:
        raise requests.exceptions.HTTPError(
            'Получен неожиданный статус кода: '
            f'{response.status_code} при запросе к {ENDPOINT}'
        )
    try:
        return response.json()
    except ValueError as error:
        raise ResponseValidationError(
            f'Невалидный JSON в ответе API: {error}'
        ) from error


def check_response(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Проверяет ответ API на соответствие документации.

    В качестве параметра функция получает ответ API,
    приведённый к типам данных Python.
    """
    if not isinstance(response, dict):
        raise TypeError('Ответ API не является словарем')
    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks"')
    if not isinstance(response['homeworks'], list):
        raise TypeError('Значение ключа "homeworks" не является списком')
    if 'current_date' not in response:
        raise KeyError('В ответе API отсутствует ключ "current_date".')
    homeworks = response['homeworks']
    if not homeworks:
        logger.debug('В ответе API отсутствуют новые статусы домашней работы.')
    return homeworks


def parse_status(homework: Dict[str, Any]) -> str:
    """Получает статус работы.

    Извлекает из информации о конкретной домашней работе
    статус этой работы.
    """
    if not isinstance(homework, dict):
        raise TypeError('Элемент домашней работы не является словарем.')
    if 'homework_name' not in homework:
        raise KeyError('Отсутствует ключ "homework_name" в "homework".')
    if 'status' not in homework:
        raise KeyError('Отсутствует ключ "status" в "homework".')
    homework_name = homework['homework_name']
    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус домашней работы: "{status}".')
    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main() -> None:
    """Основная логика работы бота."""
    last_error_message = None
    last_homework_status_message = None
    missing_tokens = check_tokens()
    if missing_tokens:
        error_message = (
            'Отсутствуют обязательные переменные окружения: '
            f'{", ".join(missing_tokens)}. Программа остановлена.'
        )
        logger.critical(error_message)
        sys.exit(error_message)
    else:
        logger.debug('Все необходимые переменные окружения доступны.')
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
                latest_homework = homeworks[0]
                message_text = parse_status(latest_homework)
                if message_text != last_homework_status_message:
                    send_message(bot, message_text)
                    last_homework_status_message = message_text
            else:
                logger.debug('Нет новых статусов домашних работ.')
            timestamp = response.get('current_date', timestamp)
        except Exception as error:
            current_error_message = f'Сбой в работе программы: {error}'
            logger.error(current_error_message, exc_info=True)
            if current_error_message != last_error_message:
                send_message(bot, current_error_message)
                last_error_message = current_error_message
        finally:
            logger.info(
                f'Ожидание {RETRY_PERIOD} секунд перед следующим запросом.'
            )
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
