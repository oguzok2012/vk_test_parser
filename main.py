import requests
import json
from bs4 import BeautifulSoup
import undetected_chromedriver as uc


class TestScraper:
    def __init__(self):
        # Инициализируем Selenium (можно добавить опции для скрытия браузера, но пока нам нужен UI для авторизации)
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")

        # Меняем стратегию загрузки: 'eager' означает, что скрипт продолжит работу,
        # как только загрузится структура DOM (не дожидаясь всех картинок и рекламы)
        options.page_load_strategy = 'eager'
        # профиль гугла ~/Application Support/... надо скопировать текущий
        #options.add_argument(r"--user-data-dir=/Users/name/all/python_proj/for_test/avito_pars/bot_profile")
        options.add_argument(r"--profile-directory=Default")  # или "Profile 1"

        driver = uc.Chrome(options=options, version_main=137)

        # Устанавливаем максимальное время ожидания загрузки страницы — 30 секунд
        driver.set_page_load_timeout(30)
        self.driver = driver
        self.session = requests.Session()

    def clean_html(self, raw_html):
        """Очищает текст от HTML тегов (span, strong, br и т.д.)"""
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    def get_cookies_from_selenium(self):
        selenium_cookies = self.driver.get_cookies()
        csrf_token = None

        for cookie in selenium_cookies:
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            # Ищем CSRF токен для POST запросов
            if cookie['name'] == 'csrftoken':
                csrf_token = cookie['value']

        headers = {
            'User-Agent': self.driver.execute_script("return navigator.userAgent;"),
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://techno-test.vk.company',
            'Referer': self.driver.current_url
        }

        # Если нашли CSRF токен, обязательно добавляем его в заголовки
        if csrf_token:
            headers['X-CSRFToken'] = csrf_token

        self.session.headers.update(headers)

    def run(self, test_url, test_id):
        print(f"Открываю браузер. Авторизуйся и открой страницу с кнопкой 'Начать тест'.")
        self.driver.get(test_url)

        input("Нажми Enter в консоли, когда страница загрузится (нажимать 'Начать' в браузере НЕ НУЖНО)...")
        self.get_cookies_from_selenium()

        # --- ШАГ 1: Пытаемся получить текущее состояние теста ---
        api_url = f"https://techno-test.vk.company/api/test/{test_id}/"
        response = self.session.get(api_url)

        # --- ШАГ 2: Если попытки нет (404), стартуем новую ---
        if response.status_code == 404:
            print("Актуальная попытка не найдена. Инициирую старт теста...")
            start_url = f"https://techno-test.vk.company/api/start_attempt/{test_id}/"

            start_response = self.session.post(start_url)

            if start_response.status_code not in (200, 201, 204):
                print(f"Критическая ошибка при старте теста: HTTP {start_response.status_code}")
                print(f"Ответ сервера: {start_response.text}")
                # Если здесь 403 - значит проблема с CSRF
                self.driver.quit()
                return

            print("Тест успешно начат. Запрашиваю данные...")
            # Повторяем GET запрос, теперь он должен вернуть 200
            response = self.session.get(api_url)

        if response.status_code != 200:
            print(f"Ошибка получения теста: {response.status_code} - {response.text}")
            self.driver.quit()
            return

        data = response.json()
        part_answers = data.get("participant_answers", [])
        current_question = data.get("question")

        # Находим индекс текущего вопроса (чтобы не начинать с 0, если тест был прерван)
        # Ищем первый id в participant_answers, у которого value равно null
        question_index = 0
        for i, pa in enumerate(part_answers):
            if pa.get("value") is None:
                question_index = i
                break

        # --- ШАГ 3: Основной цикл ---
        while current_question:
            if question_index >= len(part_answers):
                print("Похоже, это был последний вопрос. Тест завершен.")
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

        print("\nСкрапинг завершен. Закрываю браузер.")
        self.driver.quit()

if __name__ == "__main__":
    scraper = TestScraper()
    TEST_ID = "3034" # 3030 - первый тест. дальше инкремент
    #TARGET_URL = f"https://techno-test.vk.company/ru/test/?token=TOKEN&test_id={TEST_ID}"
    TARGET_URL = f"https://techno-test.vk.company/ru/test/?test_id={TEST_ID}"

    scraper.run(TARGET_URL, TEST_ID)