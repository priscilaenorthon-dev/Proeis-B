import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

LOG_DIR = Path("logs")


class _Tee:
    """Escreve simultaneamente em múltiplos streams (ex: stdout + arquivo de log)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


def _setup_log() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{ts}_http.log"
    log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)
    return log_path


BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")
MENU_URL = urljoin(BASE_URL, "FrmMenuVoluntario.aspx")
INSCRICOES_URL = urljoin(BASE_URL, "FrmVoluntarioInscricoesConsultar.aspx")
ASSOCIAR_URL = urljoin(BASE_URL, "FrmEventoAssociar.aspx")
DEBUG_DIR = Path("debug_html")


class AutomationError(RuntimeError):
    pass


@dataclass
class Candidate:
    label: str
    action: str
    payload: dict[str, str]
    score: int


def norm(value: str | None) -> str:
    value = value or ""
    value = value.replace("\u00ba", "o").replace("\u00b0", "o")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value.lower()).strip()


def normalize_captcha_answer(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def is_valid_captcha_answer(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{6}", normalize_captcha_answer(value)))


def coerce_scan_rounds(value: int) -> int:
    return max(1, int(value))


def next_scan_date_index(current_index: int, found_candidate: bool) -> int:
    return current_index if found_candidate else current_index + 1


def display_date_for_log(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return normalize_date_for_site(value)


def emit_vaga(label: str, data_evento: str = "", acao: str = "Visualizacao") -> None:
    print("[VAGA] " + json.dumps({"data": display_date_for_log(data_evento), "acao": acao, "label": label}, ensure_ascii=False))


class ProeisHTTP:
    def __init__(self, login: str, password: str, captcha_key: str, debug: bool = True):
        self.login = login
        self.password = password
        self.captcha_key = captcha_key
        self.debug = debug
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
                "Origin": BASE_URL.rstrip("/"),
                "Referer": DEFAULT_URL,
            }
        )
        self.last_url = DEFAULT_URL
        self.soup: BeautifulSoup | None = None
        self.last_captcha_id: str | None = None

    def request(self, method: str, url: str, **kwargs) -> BeautifulSoup:
        last_error: Exception | None = None
        max_attempts = int(os.getenv("PROEIS_HTTP_ATTEMPTS", "2"))
        connect_timeout = int(os.getenv("PROEIS_CONNECT_TIMEOUT", "8"))
        read_timeout = int(os.getenv("PROEIS_READ_TIMEOUT", "25"))
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"Acessando {url} ({attempt}/{max_attempts})...")
                response = self.session.request(method, url, timeout=(connect_timeout, read_timeout), **kwargs)
                response.raise_for_status()
                self.last_url = response.url
                self.soup = BeautifulSoup(response.text, "html.parser")
                self.save_debug(response.text)
                return self.soup
            except requests.RequestException as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                wait = 2
                print(f"Falha de rede acessando {url}; nova tentativa em {wait}s ({attempt}/{max_attempts}): {exc}")
                time.sleep(wait)
        raise AutomationError(f"Falha de rede acessando {url}: {last_error}")

    def save_debug(self, html: str) -> None:
        if not self.debug:
            return
        DEBUG_DIR.mkdir(exist_ok=True)
        page_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.last_url.split("/")[-1] or "page")
        filename = f"{int(time.time() * 1000)}_{page_name}.html"
        (DEBUG_DIR / filename).write_text(html, encoding="utf-8", errors="ignore")

    def form_payload(self, soup: BeautifulSoup | None = None) -> dict[str, str]:
        soup = soup or self.require_soup()
        payload: dict[str, str] = {}
        for tag in soup.select("input[name], select[name], textarea[name]"):
            name = tag.get("name")
            if not name:
                continue
            if tag.name == "select":
                selected = tag.select_one("option[selected]")
                option = selected or tag.select_one("option")
                payload[name] = option.get("value", option.get_text(strip=True)) if option else ""
            elif tag.name == "textarea":
                payload[name] = tag.get_text()
            elif tag.get("type") in {"checkbox", "radio"}:
                if tag.has_attr("checked"):
                    payload[name] = tag.get("value", "on")
            elif tag.get("type") not in {"submit", "button", "image", "file"}:
                payload[name] = tag.get("value", "")
        return payload

    def require_soup(self) -> BeautifulSoup:
        if self.soup is None:
            raise AutomationError("Nenhuma pagina carregada.")
        return self.soup

    def post_form(self, payload: dict[str, str], url: str | None = None) -> BeautifulSoup:
        return self.request("POST", url or self.last_url, data=payload)

    def postback(self, target: str, argument: str = "") -> BeautifulSoup:
        payload = self.form_payload()
        payload["__EVENTTARGET"] = target
        payload["__EVENTARGUMENT"] = argument
        return self.post_form(payload)

    def login_flow(self) -> None:
        soup = self.request("GET", DEFAULT_URL)
        payload = self.form_payload(soup)
        payload["ddlTipoAcesso"] = "ID"
        payload["__EVENTTARGET"] = "ddlTipoAcesso"
        soup = self.post_form(payload, DEFAULT_URL)

        for attempt in range(1, 7):
            captcha = self.extract_captcha_image(soup)
            captcha_text = self.solve_captcha(captcha)

            payload = self.form_payload(soup)
            payload.update(
                {
                    "ddlTipoAcesso": "ID",
                    "txtLogin": self.login,
                    "txtSenha": self.password_for_form(soup),
                    "TextCaptcha": captcha_text,
                    "btnEntrar": "Avançar",
                }
            )
            soup = self.post_form(payload, DEFAULT_URL)
            page_text = norm(soup.get_text(" ", strip=True))
            if not soup.select_one("#txtSenha") and not soup.select_one("#TextCaptcha"):
                print("Login realizado.")
                return
            if "senha invalida" in page_text:
                raise AutomationError("Login recusado: senha invalida.")
            if "erro ao confirmar imagem" in page_text:
                self.report_bad_captcha()
                print(f"Captcha de login recusado pelo site; tentando novamente ({attempt}/6).")
                continue
            raise AutomationError("Login nao saiu da tela inicial. Veja debug_html para a mensagem do site.")
        raise AutomationError("Captcha de login falhou em todas as tentativas.")

    def password_for_form(self, soup: BeautifulSoup) -> str:
        field = soup.select_one("#txtSenha") or soup.select_one('input[name="txtSenha"]')
        max_length = field.get("maxlength") if field else None
        if max_length and max_length.isdigit():
            limit = int(max_length)
            if limit > 0 and len(self.password) > limit:
                print(f"Senha maior que maxlength={limit}; enviando como o navegador enviaria.")
                return self.password[:limit]
        return self.password

    def extract_captcha_image(self, soup: BeautifulSoup) -> bytes:
        html = str(soup)
        match = re.search(r"data:image/png;base64,([^'\";)]+)", html)
        if not match:
            raise AutomationError("Nao encontrei a imagem do captcha no HTML.")
        return base64.b64decode(match.group(1))

    def solve_captcha(self, image: bytes) -> str:
        attempts = int(os.getenv("TWOCAPTCHA_INVALID_RETRIES", "2")) + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                return self.solve_captcha_once(image)
            except AutomationError as exc:
                last_error = str(exc)
                if "resposta invalida" not in last_error or attempt == attempts:
                    raise
                print(f"2captcha retornou resposta fora do padrao; reenviando captcha ({attempt}/{attempts}).")
        raise AutomationError(last_error or "2captcha nao retornou uma resposta valida.")

    def solve_captcha_once(self, image: bytes) -> str:
        print("Enviando captcha para 2captcha...")
        submit_timeout = int(os.getenv("TWOCAPTCHA_SUBMIT_TIMEOUT", "45"))
        result_timeout = int(os.getenv("TWOCAPTCHA_RESULT_TIMEOUT", "30"))
        response = requests.post(
            "https://2captcha.com/in.php",
            data={
                "key": self.captcha_key,
                "method": "base64",
                "body": base64.b64encode(image).decode("ascii"),
                "json": 1,
                "regsense": 1,
                "numeric": 4,
                "min_len": 6,
                "max_len": 6,
            },
            timeout=submit_timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != 1:
            raise AutomationError(f"2captcha recusou envio: {data}")
        captcha_id = data["request"]
        self.last_captcha_id = captcha_id
        initial_wait = float(os.getenv("TWOCAPTCHA_INITIAL_WAIT", "5"))
        poll_interval = float(os.getenv("TWOCAPTCHA_POLL_INTERVAL", "1.5"))
        max_wait = float(os.getenv("TWOCAPTCHA_MAX_WAIT", "75"))
        deadline = time.monotonic() + max_wait
        time.sleep(initial_wait)
        while time.monotonic() < deadline:
            result = requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.captcha_key, "action": "get", "id": captcha_id, "json": 1},
                timeout=result_timeout,
            )
            result.raise_for_status()
            solved = result.json()
            if solved.get("status") == 1:
                text = normalize_captcha_answer(solved["request"])
                if not is_valid_captcha_answer(text):
                    self.report_bad_captcha()
                    raise AutomationError(f"2captcha retornou resposta invalida para captcha de 6 caracteres: {text or solved.get('request')}")
                print(f"Captcha resolvido: {text}")
                return text
            if solved.get("request") != "CAPCHA_NOT_READY":
                raise AutomationError(f"2captcha retornou erro: {solved}")
            time.sleep(poll_interval)
        raise AutomationError("2captcha nao respondeu em tempo util.")

    def normalize_captcha_answer(self, value: str) -> str:
        return normalize_captcha_answer(value)

    def report_bad_captcha(self) -> None:
        if not self.last_captcha_id:
            return
        try:
            requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.captcha_key, "action": "reportbad", "id": self.last_captcha_id, "json": 1},
                timeout=15,
            )
        except requests.RequestException:
            pass

    def navigate_to_service_page(self) -> None:
        soup = self.request("GET", MENU_URL)
        if soup.select_one("#btnEscala") or "btnEscala" in str(soup):
            soup = self.postback("btnEscala")
        if self.has_service_fields(soup):
            print("Tela de associar voluntario encontrada.")
            return
        new_subscription = self.find_action_by_text(soup, ("nova inscricao", "nova inscrição"))
        if new_subscription:
            print("Abrindo Nova Inscricao.")
            if new_subscription.action == "postback":
                soup = self.postback(new_subscription.payload["target"], new_subscription.payload.get("argument", ""))
            elif new_subscription.action == "submit":
                soup = self.post_form(new_subscription.payload)
            else:
                soup = self.request("GET", new_subscription.action)
            if self.has_service_fields(soup):
                print("Tela de associar voluntario encontrada.")
                return

        keywords = (
            "inscricao",
            "inscrever",
            "servico",
            "servicos",
            "evento",
            "eventos",
            "escala",
            "minhas inscricoes",
        )
        for _ in range(6):
            soup = self.require_soup()
            if self.has_service_fields(soup):
                print("Tela de servico encontrada.")
                return
            candidate = self.best_navigation_link(soup, keywords)
            if not candidate:
                break
            print(f"Navegando: {candidate.label}")
            if candidate.action == "postback":
                self.postback(candidate.payload["target"], candidate.payload.get("argument", ""))
            else:
                self.request("GET", candidate.action)
        raise AutomationError("Nao encontrei a tela de marcacao. Veja os HTMLs em debug_html.")

    def find_action_by_text(self, soup: BeautifulSoup, keywords: Iterable[str]) -> Candidate | None:
        for link in soup.select("a[href]"):
            label = link.get_text(" ", strip=True) or link.get("title") or link.get("id") or ""
            if any(keyword in norm(label) for keyword in keywords):
                action = self.link_action(link)
                if action:
                    return Candidate(label, action[0], action[1], 100)
        for control in soup.select("input[type=submit][name], button[name]"):
            label = " ".join([control.get_text(" ", strip=True), control.get("value", ""), control.get("id", ""), control.get("name", "")])
            if any(keyword in norm(label) for keyword in keywords):
                payload = self.form_payload(soup)
                payload[control.get("name")] = control.get("value", "")
                return Candidate(label, "submit", payload, 100)
        return None

    def best_navigation_link(self, soup: BeautifulSoup, keywords: Iterable[str]) -> Candidate | None:
        candidates: list[Candidate] = []
        for link in soup.select("a[href]"):
            label = link.get_text(" ", strip=True) or link.get("title") or link.get("id") or ""
            label_norm = norm(label + " " + (link.get("href") or ""))
            score = sum(10 for kw in keywords if kw in label_norm)
            if score == 0:
                continue
            href = link["href"]
            postback = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", href)
            if postback:
                candidates.append(
                    Candidate(label, "postback", {"target": postback.group(1), "argument": postback.group(2)}, score)
                )
            elif not href.startswith("#") and not href.lower().startswith("javascript:"):
                candidates.append(Candidate(label, urljoin(self.last_url, href), {}, score))
        return sorted(candidates, key=lambda item: item.score, reverse=True)[0] if candidates else None

    def has_service_fields(self, soup: BeautifulSoup) -> bool:
        text = norm(soup.get_text(" ", strip=True))
        return ("convenio" in text or "convênio" in text) and ("cpa" in text or "data do evento" in text)

    def fill_filters(self, convenio: str, data_evento: str, cpa: str) -> None:
        soup = self.require_soup()
        fields = self.find_fields(soup)

        payload = self.form_payload(soup)
        self.set_field(payload, fields, "convenio", convenio)
        payload["__EVENTTARGET"] = fields["convenio"]
        payload["__EVENTARGUMENT"] = ""
        soup = self.post_form(payload)

        for attempt in range(1, 7):
            payload = self.form_payload(soup)
            fields = self.find_fields(soup)
            self.set_field(payload, fields, "data", normalize_date_for_site(data_evento))
            self.set_field(payload, fields, "cpa", cpa)
            self.fill_page_captcha(soup, payload)
            self.set_reserva_checkbox(soup, payload, True)
            submit = self.find_submit(soup, ("pesquisar", "buscar", "consultar", "filtrar", "listar", "avancar"))
            if submit:
                payload[submit] = self.input_value(soup, submit)
            print("Consultando disponibilidade...")
            soup = self.post_form(payload)
            if "erro ao confirmar imagem" in norm(str(soup)):
                self.report_bad_captcha()
                print(f"Captcha de filtro recusado pelo site; tentando novamente ({attempt}/6).")
                continue
            return
        raise AutomationError("Captcha do filtro falhou em todas as tentativas.")

    def fill_filters_first_matching_date(self, convenio: str, cpa: str, prefer: str, scan_rounds: int = 1) -> str:
        soup = self.require_soup()
        fields = self.find_fields(soup)

        payload = self.form_payload(soup)
        self.set_field(payload, fields, "convenio", convenio)
        payload["__EVENTTARGET"] = fields["convenio"]
        payload["__EVENTARGUMENT"] = ""
        soup = self.post_form(payload)

        fields = self.find_fields(soup)
        date_field = fields.get("data")
        if not date_field:
            raise AutomationError("Nao encontrei o campo de data para varredura.")

        date_select = soup.select_one(f'select[name="{date_field}"]')
        if not date_select:
            raise AutomationError("Campo de data nao e um select; informe --data-evento manualmente.")

        dates = [
            (option.get("value", ""), option.get_text(" ", strip=True))
            for option in date_select.select("option")
            if option.get("value", "") not in {"", "0"} and norm(option.get_text(" ", strip=True)) != "selecione"
        ]
        if not dates:
            raise AutomationError("Nenhuma data disponivel no select.")

        scan_rounds = coerce_scan_rounds(scan_rounds)
        for scan_round in range(1, scan_rounds + 1):
            if scan_rounds > 1:
                print(f"Rodada de varredura {scan_round}/{scan_rounds}.")
            for value, label in dates:
                print(f"Testando data disponivel: {label}")
                for attempt in range(1, 7):
                    payload = self.form_payload(soup)
                    fields = self.find_fields(soup)
                    payload[fields["data"]] = value
                    self.set_field(payload, fields, "cpa", cpa)
                    self.fill_page_captcha(soup, payload)
                    self.set_reserva_checkbox(soup, payload, True)
                    submit = self.find_submit(soup, ("pesquisar", "buscar", "consultar", "filtrar", "listar", "avancar"))
                    if submit:
                        payload[submit] = self.input_value(soup, submit)
                    print("Consultando disponibilidade...")
                    result_soup = self.post_form(payload)
                    if "erro ao confirmar imagem" in norm(str(result_soup)):
                        self.report_bad_captcha()
                        print(f"Captcha de filtro recusado pelo site; tentando novamente ({attempt}/6).")
                        soup = result_soup
                        continue
                    if self.available_candidates(result_soup, prefer):
                        print(f"Data com vaga encontrada: {label}")
                        return label
                    print(f"Nenhuma vaga do tipo solicitado em {label}.")
                    self.navigate_to_service_page()
                    soup = self.require_soup()
                    payload = self.form_payload(soup)
                    fields = self.find_fields(soup)
                    self.set_field(payload, fields, "convenio", convenio)
                    payload["__EVENTTARGET"] = fields["convenio"]
                    payload["__EVENTARGUMENT"] = ""
                    soup = self.post_form(payload)
                    break
        raise AutomationError("Nenhuma data disponivel tinha vaga do tipo solicitado.")

    def dates_for_convenio(self, convenio: str) -> list[tuple[str, str]]:
        soup = self.require_soup()
        fields = self.find_fields(soup)

        payload = self.form_payload(soup)
        self.set_field(payload, fields, "convenio", convenio)
        payload["__EVENTTARGET"] = fields["convenio"]
        payload["__EVENTARGUMENT"] = ""
        soup = self.post_form(payload)

        dates = self.available_date_options(soup)
        if not dates:
            raise AutomationError("Nenhuma data disponivel no select.")
        return dates

    def mark_scanning_dates(
        self,
        convenio: str,
        cpa: str,
        prefer: str,
        quantidade: int,
        scan_rounds: int = 1,
        nome_evento: str = "",
        hora_evento: str = "",
        turno: str = "",
        endereco: str = "",
    ) -> int:
        self.navigate_to_service_page()
        dates = self.dates_for_convenio(convenio)
        print(f"[VAGAS] Marcacao por varredura iniciada: {len(dates)} data(s) disponivel(is).")

        confirmed = 0
        scan_rounds = coerce_scan_rounds(scan_rounds)
        for scan_round in range(1, scan_rounds + 1):
            if confirmed >= quantidade:
                break
            if scan_rounds > 1:
                print(f"Rodada de varredura {scan_round}/{scan_rounds}.")

            date_index = 0
            while date_index < len(dates) and confirmed < quantidade:
                _, label = dates[date_index]
                print(f"Testando data disponivel: {label}")
                self.navigate_to_service_page()
                self.fill_filters(convenio, label, cpa)
                candidates = self.available_candidates(self.require_soup(), prefer)
                if not candidates:
                    print(f"Nenhuma vaga do tipo solicitado em {label}.")
                    date_index = next_scan_date_index(date_index, found_candidate=False)
                    continue

                print(f"Tentativa de marcacao {confirmed + 1}/{quantidade}.")
                success = self.choose_target_event(
                    prefer,
                    False,
                    data_evento=label,
                    nome_evento=nome_evento,
                    hora_evento=hora_evento,
                    turno=turno,
                    endereco=endereco,
                )
                if not success:
                    raise AutomationError("Clique executado, mas nao encontrei confirmacao de sucesso no retorno do site.")
                confirmed += 1
                print(f"Marcacoes confirmadas: {confirmed}/{quantidade}.")
                date_index = next_scan_date_index(date_index, found_candidate=True)

        return confirmed

    def list_all_available_dates(self, convenio: str, cpa: str) -> int:
        soup = self.require_soup()
        fields = self.find_fields(soup)

        payload = self.form_payload(soup)
        self.set_field(payload, fields, "convenio", convenio)
        payload["__EVENTTARGET"] = fields["convenio"]
        payload["__EVENTARGUMENT"] = ""
        soup = self.post_form(payload)

        dates = self.available_date_options(soup)
        print(f"[VAGAS] Varredura iniciada: {len(dates)} data(s) disponivel(is).")

        total = 0
        for value, label in dates:
            print(f"Listando data: {label}")
            for attempt in range(1, 7):
                payload = self.form_payload(soup)
                fields = self.find_fields(soup)
                payload[fields["data"]] = value
                self.set_field(payload, fields, "cpa", cpa)
                self.fill_page_captcha(soup, payload)
                self.set_reserva_checkbox(soup, payload, True)
                submit = self.find_submit(soup, ("pesquisar", "buscar", "consultar", "filtrar", "listar", "avancar"))
                if submit:
                    payload[submit] = self.input_value(soup, submit)
                print("Consultando disponibilidade...")
                result_soup = self.post_form(payload)
                if "erro ao confirmar imagem" in norm(str(result_soup)):
                    self.report_bad_captcha()
                    print(f"Captcha de filtro recusado pelo site; tentando novamente ({attempt}/6).")
                    soup = result_soup
                    continue

                candidates = self.available_candidates(result_soup, "qualquer")
                if candidates:
                    print(f"[VAGAS] {len(candidates)} vaga(s) encontrada(s) em {label}:")
                    for candidate in candidates:
                        emit_vaga(candidate.label, data_evento=label, acao="Visualizacao")
                    total += len(candidates)
                else:
                    print(f"Nenhuma vaga encontrada em {label}.")
                break

            self.navigate_to_service_page()
            soup = self.require_soup()
            payload = self.form_payload(soup)
            fields = self.find_fields(soup)
            self.set_field(payload, fields, "convenio", convenio)
            payload["__EVENTTARGET"] = fields["convenio"]
            payload["__EVENTARGUMENT"] = ""
            soup = self.post_form(payload)

        print(f"[VAGAS] Varredura concluida: {total} vaga(s) encontrada(s) no total.")
        return total

    def available_date_options(self, soup: BeautifulSoup) -> list[tuple[str, str]]:
        fields = self.find_fields(soup)
        date_field = fields.get("data")
        if not date_field:
            raise AutomationError("Nao encontrei o campo de data para varredura.")
        date_select = soup.select_one(f'select[name="{date_field}"]')
        if not date_select:
            raise AutomationError("Campo de data nao e um select.")
        dates = [
            (option.get("value", ""), option.get_text(" ", strip=True))
            for option in date_select.select("option")
            if option.get("value", "") not in {"", "0"} and norm(option.get_text(" ", strip=True)) != "selecione"
        ]
        if not dates:
            raise AutomationError("Nenhuma data disponivel no select.")
        return dates

    def fill_page_captcha(self, soup: BeautifulSoup, payload: dict[str, str]) -> None:
        captcha_field = self.find_captcha_field(soup)
        if not captcha_field:
            return
        captcha = self.extract_captcha_image(soup)
        payload[captcha_field] = self.solve_captcha(captcha)

    def find_captcha_field(self, soup: BeautifulSoup) -> str | None:
        for control in soup.select("input[name]"):
            name = control.get("name", "")
            text = norm(
                " ".join(
                    [
                        name,
                        control.get("id", ""),
                        control.get("placeholder", ""),
                        self.label_for(soup, control.get("id")),
                        self.near_text(control),
                    ]
                )
            )
            if "caracteres da imagem" in text or "captcha" in text:
                return name
        return None

    def set_reserva_checkbox(self, soup: BeautifulSoup, payload: dict[str, str], enabled: bool) -> None:
        for checkbox in soup.select('input[type="checkbox"][name]'):
            text = norm(
                " ".join(
                    [
                        checkbox.get("name", ""),
                        checkbox.get("id", ""),
                        self.label_for(soup, checkbox.get("id")),
                        self.near_text(checkbox),
                    ]
                )
            )
            if "reserva" in text:
                if enabled:
                    payload[checkbox["name"]] = checkbox.get("value", "on")
                else:
                    payload.pop(checkbox["name"], None)

    def find_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        known_ids = {
            "ddlConvenios": "convenio",
            "ddlDataEvento": "data",
            "ddlCPAS": "cpa",
        }
        for control_id, logical in known_ids.items():
            control = soup.select_one(f"#{control_id}")
            if control and control.get("name"):
                fields[logical] = control["name"]
        controls = soup.select("input[name], select[name], textarea[name]")
        for control in controls:
            name = control.get("name")
            if not name:
                continue
            text = " ".join(
                [
                    control.get("id", ""),
                    name,
                    control.get("placeholder", ""),
                    control.get("aria-label", ""),
                    self.label_for(soup, control.get("id")),
                    self.near_text(control),
                ]
            )
            key = norm(text)
            if ("convenio" in key or "convênio" in key) and "convenio" not in fields:
                fields["convenio"] = name
            elif ("data do evento" in key or ("data" in key and "evento" in key)) and "data" not in fields:
                fields["data"] = name
            elif re.search(r"\bcpa\b", key) and "cpa" not in fields:
                fields["cpa"] = name
        return fields

    def label_for(self, soup: BeautifulSoup, control_id: str | None) -> str:
        if not control_id:
            return ""
        label = soup.select_one(f'label[for="{control_id}"]')
        return label.get_text(" ", strip=True) if label else ""

    def near_text(self, tag) -> str:
        texts = []
        parent = tag.parent
        for _ in range(3):
            if not parent:
                break
            texts.append(parent.get_text(" ", strip=True)[:200])
            parent = parent.parent
        return " ".join(texts)

    def set_field(self, payload: dict[str, str], fields: dict[str, str], logical: str, desired: str) -> None:
        name = fields.get(logical)
        if not name:
            raise AutomationError(f"Nao encontrei o campo {logical}. Veja debug_html.")
        soup = self.require_soup()
        select = soup.select_one(f'select[name="{name}"]')
        if select:
            payload[name] = self.option_value(select, desired)
        else:
            payload[name] = desired

    def option_value(self, select, desired: str) -> str:
        desired_norm = norm(desired)
        options = select.select("option")
        for option in options:
            text = norm(option.get_text(" ", strip=True))
            value = norm(option.get("value", ""))
            if desired_norm == text or desired_norm == value:
                return option.get("value", option.get_text(strip=True))
        for option in options:
            text = norm(option.get_text(" ", strip=True))
            value = norm(option.get("value", ""))
            if desired_norm in text or desired_norm in value:
                return option.get("value", option.get_text(strip=True))
        raise AutomationError(f"Opcao '{desired}' nao encontrada no select {select.get('name')}.")

    def find_submit(self, soup: BeautifulSoup, keywords: Iterable[str]) -> str | None:
        for tag in soup.select("input[type=submit][name], button[name]"):
            text = norm(" ".join([tag.get("value", ""), tag.get_text(" ", strip=True), tag.get("id", ""), tag.get("name", "")]))
            if any(keyword in text for keyword in keywords):
                return tag.get("name")
        return None

    def input_value(self, soup: BeautifulSoup, name: str) -> str:
        tag = soup.select_one(f'[name="{name}"]')
        return tag.get("value", "") if tag else ""

    def choose_available(self, prefer: str, dry_run: bool, data_evento: str = "") -> None:
        soup = self.require_soup()
        candidates = self.available_candidates(soup, prefer)
        if not candidates:
            raise AutomationError("Nenhuma opcao disponivel/reserva encontrada para os filtros.")
        chosen = candidates[0]
        print(f"[VAGAS] {min(len(candidates), 10)} vaga(s) encontrada(s):")
        for c in candidates[:10]:
            emit_vaga(c.label, data_evento=data_evento, acao="Visualizacao")
        print(f"Escolhida: {chosen.label}")
        if dry_run:
            print("dry_run=true: nao confirmei a marcacao.")
            return
        if chosen.action == "postback":
            soup = self.postback(chosen.payload["target"], chosen.payload.get("argument", ""))
        elif chosen.action == "submit":
            soup = self.post_form(chosen.payload)
        else:
            soup = self.request("GET", chosen.action)
        self.confirm_if_needed(soup)

    def choose_target_event(
        self,
        prefer: str,
        dry_run: bool,
        data_evento: str = "",
        nome_evento: str = "",
        hora_evento: str = "",
        turno: str = "",
        endereco: str = "",
    ) -> bool:
        soup = self.require_soup()
        candidates = self.available_candidates(soup, prefer)
        filtered = [
            candidate
            for candidate in candidates
            if self.event_matches(candidate.label, nome_evento, hora_evento, turno, endereco)
        ]
        if not filtered:
            print(f"[VAGAS] {len(candidates)} opcao(oes) disponivel(is) encontrada(s):")
            for c in candidates[:20]:
                emit_vaga(c.label, data_evento=data_evento, acao="Visualizacao")
            raise AutomationError("Nao encontrei a linha exata do evento solicitado.")
        chosen = filtered[0]
        print(f"[VAGAS] {len(filtered)} vaga(s) encontrada(s):")
        if dry_run:
            for c in filtered:
                emit_vaga(c.label, data_evento=data_evento, acao="Visualizacao")
            print("dry_run=true: nao cliquei em Eu Vou.")
            return False
        if chosen.action == "postback":
            soup = self.postback(chosen.payload["target"], chosen.payload.get("argument", ""))
        elif chosen.action == "submit":
            soup = self.post_form(chosen.payload)
        else:
            soup = self.request("GET", chosen.action)
        success = self.confirm_if_needed(soup)
        if success:
            emit_vaga(chosen.label, data_evento=data_evento, acao="Clicado Eu vou")
        return success

    def event_matches(self, label: str, nome_evento: str, hora_evento: str, turno: str, endereco: str) -> bool:
        label_norm = norm(label)
        checks = [
            (nome_evento, norm(nome_evento) in label_norm),
            (hora_evento, norm(hora_evento) in label_norm),
            (turno, norm(turno) in label_norm),
            (endereco, norm(endereco) in label_norm),
        ]
        active = [matches for raw, matches in checks if raw]
        return all(active) if active else True

    def available_candidates(self, soup: BeautifulSoup, prefer: str) -> list[Candidate]:
        prefer_norm = norm(prefer)
        candidates: list[Candidate] = []
        for row in soup.select("tr"):
            text = row.get_text(" ", strip=True)
            text_norm = norm(text)
            if not self.matches_preference(text_norm, prefer_norm):
                continue
            action = self.row_action(row)
            if action:
                candidates.append(Candidate(text[:240], action[0], action[1], self.preference_score(text_norm, prefer_norm)))
        for link in soup.select("a[href]"):
            text = link.get_text(" ", strip=True)
            text_norm = norm(text)
            if self.matches_preference(text_norm, prefer_norm):
                action = self.link_action(link)
                if action:
                    candidates.append(Candidate(text[:240], action[0], action[1], self.preference_score(text_norm, prefer_norm)))
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def matches_preference(self, text: str, prefer: str) -> bool:
        if prefer in {"nao-reserva", "sem-reserva", "normal"}:
            return "reserva" not in text and re.search(r"\b\d+\s*-\s*curso", text) is not None
        if prefer in {"qualquer", "any", ""}:
            return "disponivel" in text or "reserva" in text or re.search(r"\b\d+\s*-\s*curso", text) is not None
        if prefer == "reserva":
            return "reserva" in text
        return re.search(rf"\b{re.escape(prefer)}\b", text) is not None or f"disponivel {prefer}" in text

    def preference_score(self, text: str, prefer: str) -> int:
        if prefer in {"nao-reserva", "sem-reserva", "normal"} and "reserva" not in text:
            match = re.search(r"\b(\d+)\s*-\s*curso", text)
            return 100 - int(match.group(1)) if match else 80
        if prefer == "reserva" and "reserva" in text:
            return 100
        if prefer not in {"qualquer", "any", ""} and re.search(rf"\b{re.escape(prefer)}\b", text):
            return 100
        if "disponivel" in text:
            return 50
        if "reserva" in text:
            return 40
        return 10

    def row_action(self, row) -> tuple[str, dict[str, str]] | None:
        for control in row.select("a[href], input[type=submit][name], button[name]"):
            text = norm(" ".join([control.get_text(" ", strip=True), control.get("value", ""), control.get("id", ""), control.get("name", "")]))
            if not any(
                word in text
                for word in ("eu vou", "inscrever", "marcar", "reservar", "confirmar", "selecionar", "participar")
            ):
                continue
            if control.name == "a":
                return self.link_action(control)
            payload = self.form_payload()
            payload[control.get("name")] = control.get("value", "")
            return ("submit", payload)
        return None

    def link_action(self, link) -> tuple[str, dict[str, str]] | None:
        href = link.get("href", "")
        postback = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", href)
        if postback:
            return ("postback", {"target": postback.group(1), "argument": postback.group(2)})
        if href and not href.startswith("#") and not href.lower().startswith("javascript:"):
            return (urljoin(self.last_url, href), {})
        return None

    def confirm_if_needed(self, soup: BeautifulSoup) -> bool:
        text = norm(soup.get_text(" ", strip=True))
        if any(word in text for word in ("confirmar", "confirma", "deseja")):
            submit = self.find_submit(soup, ("confirmar", "sim", "concluir", "finalizar"))
            if submit:
                payload = self.form_payload(soup)
                payload[submit] = self.input_value(soup, submit)
                soup = self.post_form(payload)
        final_text = soup.get_text(" ", strip=True)
        page_text = norm(str(soup))
        success = any(
            term in page_text
            for term in (
                "confirmacao no evento foi incluida com sucesso",
                "confirmacao no evento foi incluida",
                "incluida com sucesso",
                "incluido com sucesso",
            )
        )
        print("Retorno final:")
        print(re.sub(r"\s+", " ", final_text)[:1200])
        if success:
            print("Marcacao confirmada pelo site.")
        return success


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise AutomationError(f"Variavel/secret obrigatorio ausente: {name}")
    return value


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def normalize_date_for_site(value: str) -> str:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automacao HTTP puro PROEIS.")
    parser.add_argument("--convenio", required=True)
    parser.add_argument("--data-evento", default="")
    parser.add_argument("--cpa", required=True)
    parser.add_argument("--disponivel", choices=["reserva", "nao-reserva"], default="nao-reserva")
    parser.add_argument("--quantidade", type=int, default=1, help="Quantidade de vagas para tentar marcar.")
    parser.add_argument("--nome-evento", default="")
    parser.add_argument("--hora-evento", default="")
    parser.add_argument("--turno", default="")
    parser.add_argument("--endereco", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-all-dates", action="store_true", help="Lista vagas de todas as datas disponiveis para o convenio/CPA, sem clicar em Eu Vou.")
    parser.add_argument("--no-debug", action="store_true")
    parser.add_argument("--scan-rounds", type=int, default=1, help="Quantidade de rodadas de varredura quando a data do evento estiver vazia.")
    parser.add_argument("--wait-until", default="", help="HH:MM:SS — faz login imediatamente e aguarda ate esse horario para marcar.")
    return parser.parse_args()


def main() -> int:
    load_env_file()
    log_path = _setup_log()
    print(f"[LOG] Arquivo de log: {log_path}")
    args = parse_args()
    if args.quantidade < 1:
        raise AutomationError("--quantidade deve ser 1 ou maior.")
    if args.dry_run and args.quantidade != 1:
        print("dry_run=true: usando quantidade=1 para teste rapido.")
        args.quantidade = 1
    client = ProeisHTTP(
        login=required_env("PROEIS_LOGIN"),
        password=required_env("PROEIS_PASSWORD"),
        captcha_key=required_env("TWOCAPTCHA_API_KEY"),
        debug=not args.no_debug,
    )
    client.login_flow()

    if args.list_all_dates:
        client.navigate_to_service_page()
        client.list_all_available_dates(args.convenio, args.cpa)
        return 0

    if args.wait_until:
        try:
            t = datetime.strptime(args.wait_until, "%H:%M:%S")
        except ValueError:
            t = datetime.strptime(args.wait_until, "%H:%M")
        now = datetime.now()
        target = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_secs = int((target - datetime.now()).total_seconds())
        print(f"Login antecipado concluido. Iniciando marcacao em {wait_secs}s (horario: {target.strftime('%H:%M:%S')})...")
        while True:
            remaining = int((target - datetime.now()).total_seconds())
            if remaining <= 0:
                break
            if remaining % 10 == 0:
                print(f"  Aguardando... {remaining}s restantes.")
            time.sleep(1)
        print("Horario atingido — iniciando marcacao.")

    if not args.data_evento and not args.dry_run:
        confirmed = client.mark_scanning_dates(
            args.convenio,
            args.cpa,
            args.disponivel,
            args.quantidade,
            scan_rounds=args.scan_rounds,
            nome_evento=args.nome_evento,
            hora_evento=args.hora_evento,
            turno=args.turno,
            endereco=args.endereco,
        )
        if confirmed < args.quantidade:
            print(f"Sem mais vagas do tipo solicitado. Marcacoes confirmadas: {confirmed}/{args.quantidade}.")
        return 0

    confirmed = 0
    for index in range(1, args.quantidade + 1):
        print(f"Tentativa de marcacao {index}/{args.quantidade}.")
        client.navigate_to_service_page()
        try:
            selected_date = args.data_evento
            if args.data_evento:
                client.fill_filters(args.convenio, args.data_evento, args.cpa)
            else:
                selected_date = client.fill_filters_first_matching_date(
                    args.convenio,
                    args.cpa,
                    args.disponivel,
                    scan_rounds=args.scan_rounds,
                )
            success = client.choose_target_event(
                args.disponivel,
                args.dry_run,
                data_evento=selected_date,
                nome_evento=args.nome_evento,
                hora_evento=args.hora_evento,
                turno=args.turno,
                endereco=args.endereco,
            )
        except AutomationError:
            if confirmed:
                print(f"Sem mais vagas do tipo solicitado. Marcacoes confirmadas: {confirmed}/{args.quantidade}.")
                return 0
            raise
        if args.dry_run:
            print("dry_run=true: teste encerrado apos localizar a primeira opcao.")
            return 0
        if not success:
            raise AutomationError("Clique executado, mas nao encontrei confirmacao de sucesso no retorno do site.")
        confirmed += 1
        print(f"Marcacoes confirmadas: {confirmed}/{args.quantidade}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AutomationError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(2)
