FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY streamlit_app.py ./
COPY knight ./knight
COPY static ./static
# Download all three pinned native cores at build time, including optional tunnel support.
RUN BK_DATA_DIR=/opt/blue-knight python streamlit_app.py --install-engines \
    && useradd --uid 10001 --create-home knight \
    && mkdir -p /data && chown knight:knight /data
ENV BK_DATA_DIR=/data
USER knight
EXPOSE 8080/tcp 443/tcp 8388/tcp 8388/udp 51820/udp 8443/udp 8444/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/healthz', timeout=4)"
CMD ["python", "streamlit_app.py", "--no-download"]
