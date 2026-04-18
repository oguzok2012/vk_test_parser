import os
import requests
import json
import re
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from dotenv import load_dotenv

load_dotenv()


class TestScraper:
    def __init__(self, profile_dir, token):
        self.profile_dir = profile_dir
        self.token = token

        if not self.profile_dir:
            raise ValueError("ОШИБКА: CHROME_PROFILE_DIR не задан в .env файле!")
        if not self.token:
            raise ValueError("ОШИБКА: VK_TEST_TOKEN не задан в .env файле!")

        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.page_load_strategy = 'eager'

        # Используем путь из .env
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument(r"--profile-directory=Default")

        self.driver = uc.Chrome(options=options, version_main=137)
        self.driver.set_page_load_timeout(30)

        self.session = requests.Session()

    def clean_html(self, raw_html):
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    def get_cookies_from_selenium(self):
        selenium_cookies = self.driver.get_cookies()
        csrf_token = None

        for cookie in selenium_cookies:
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            if cookie['name'] == 'csrftoken':
                csrf_token = cookie['value']

        headers = {
            'User-Agent': self.driver.execute_script("return navigator.userAgent;"),
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://techno-test.vk.company',
            'Referer': self.driver.current_url
        }

        if csrf_token:
            headers['X-CSRFToken'] = csrf_token

        self.session.headers.update(headers)

    def fetch_and_show_menu(self):
        print("\nЗапрашиваю список доступных тестов...")
        tests_url = "https://techno-test.vk.company/api/tests/"
        response = self.session.get(tests_url)

        if response.status_code != 200:
            print(f"Ошибка получения списка тестов: HTTP {response.status_code}")
            return None

        tests_data = response.json()

        def extract_number(name):
            match = re.search(r'^(\d+)', name)
            return int(match.group(1)) if match else 9999

        tests_data.sort(key=lambda x: extract_number(x.get('name', '')))

        print("\n" + "=" * 80)
        print(f"{'ID':<6} | {'Статус':<12} | {'Прогресс':<9} | {'Название'}")
        print("-" * 80)

        for t in tests_data:
            t_id = t.get('id')
            t_name = t.get('name')
            attempt = t.get('attempt')

            if attempt is None:
                status_str = "Не начат"
                progress = "0/0"
            else:
                status_code = attempt.get('status')
                ans_count = attempt.get('answers_count', 0)
                q_count = attempt.get('questions_count', 0)
                progress = f"{ans_count}/{q_count}"

                if status_code == 1:
                    status_str = "[ЗАВЕРШЕН]"
                else:
                    status_str = "В процессе"

            short_name = t_name[:50] + "..." if len(t_name) > 50 else t_name
            print(f"{t_id:<6} | {status_str:<12} | {progress:<9} | {short_name}")

        print("=" * 80)

        while True:
            choice = input("\nВведи ID теста, который хочешь спарсить (или 'q' для выхода): ")
            if choice.lower() == 'q':
                return None
            if choice.isdigit():
                chosen_id = int(choice)
                if any(t.get('id') == chosen_id for t in tests_data):
                    return str(chosen_id)
                else:
                    print("Такого ID нет в таблице выше. Попробуй еще раз.")
            else:
                print("Пожалуйста, введи только цифры ID.")

    def run(self):
        # Формируем URL используя токен из .env
        base_url = f"https://techno-test.vk.company/ru/test/?token={self.token}"

        print(f"Открываю браузер...")
        self.driver.get(base_url)

        input("Нажми Enter в консоли, когда страница прогрузится и ты будешь авторизован...")
        self.get_cookies_from_selenium()

        test_id = self.fetch_and_show_menu()
        if not test_id:
            print("Выход. Закрываю браузер.")
            self.driver.quit()
            return

        print(f"\nНачинаю работу с тестом ID: {test_id}...")

        api_url = f"https://techno-test.vk.company/api/test/{test_id}/"
        response = self.session.get(api_url)

        if response.status_code == 404:
            print("Актуальная попытка не найдена. Инициирую старт теста...")
            start_url = f"https://techno-test.vk.company/api/start_attempt/{test_id}/"
            start_response = self.session.post(start_url)

            if start_response.status_code not in (200, 201, 204):
                print(f"Критическая ошибка при старте теста: HTTP {start_response.status_code}")
                print(f"Ответ сервера: {start_response.text}")
                self.driver.quit()
                return

            print("Тест успешно начат. Запрашиваю данные...")
            response = self.session.get(api_url)

        if response.status_code != 200:
            print(f"Ошибка получения теста: {response.status_code} - {response.text}")
            self.driver.quit()
            return

        data = response.json()
        part_answers = data.get("participant_answers", [])
        current_question = data.get("question")

        question_index = 0
        for i, pa in enumerate(part_answers):
            if pa.get("value") is None:
                question_index = i
                break

        while current_question:
            if question_index >= len(part_answers):
                print("Похоже, это был последний вопрос (или тест уже завершен). Скрапинг остановлен.")
                break

            participant_answer_id = part_answers[question_index]["id"]

            q_text = self.clean_html(current_question.get("text"))
            print("\n" + "=" * 50)
            print(f"Вопрос {question_index + 1}: {q_text}")

            answers = current_question.get("answers", [])
            for idx, ans in enumerate(answers):
                ans_text = self.clean_html(ans.get("text"))
                print(f"  [{idx + 1}] - {ans_text}")

            print("-" * 50)
            user_choice = input("Введи номер ответа (цифру), чтобы пойти дальше, или 'q' для выхода: ")

            if user_choice.lower() == 'q':
                print("Выход...")
                break

            try:
                choice_idx = int(user_choice) - 1
                selected_answer_id = answers[choice_idx]["id"]
            except (ValueError, IndexError):
                print("Неверный ввод, попробуй еще раз.")
                continue

            update_url = f"https://techno-test.vk.company/api/participant_answer/{participant_answer_id}/update/"
            payload = {"value": json.dumps([str(selected_answer_id)])}
            post_response = self.session.post(update_url, json=payload)

            if post_response.status_code == 200:
                print("Ответ принят!")
                current_question = post_response.json()
                question_index += 1
            else:
                print(f"Ошибка при отправке ответа: HTTP {post_response.status_code}")
                print(post_response.text)
                break

        print("\nРабота скрипта завершена. Закрываю браузер.")
        self.driver.quit()


if __name__ == "__main__":
    PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR")
    TOKEN = os.getenv("VK_TEST_TOKEN")

    if not PROFILE_DIR:
        raise ValueError("ОШИБКА: CHROME_PROFILE_DIR не задан в .env файле!")
    if not TOKEN:
        raise ValueError("ОШИБКА: VK_TEST_TOKEN не задан в .env файле!")

    try:
        scraper = TestScraper(
            profile_dir=PROFILE_DIR,
            token=TOKEN,
        )
        scraper.run()
    except Exception as e:
        print(f"\nКритическая ошибка: {e}")
