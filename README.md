# AI Destekli Ev Fiyatı Tahmini Algoritması

## Öğrenci Bilgileri

* Ad Soyad: Mehmet Çelebi
* Öğrenci Numarası: 24010509088

---

# Proje Hakkında

## Projenin Amacı

Bu projenin amacı, kullanıcıların belirli bir bölgede bulunan gayrimenkullerin güncel piyasa değerlerini ve gelecekteki tahmini değerlerini yapay zeka destekli analiz yöntemleriyle tahmin edebilmelerini sağlamaktır.

## Kısa Açıklama

Proje, çeşitli emlak ilan sitelerinden elde edilen verileri analiz ederek belirlenen bölgedeki konutların fiyatlarını değerlendirmektedir. Kullanıcı web arayüzü üzerinden bir bölge seçtikten sonra sistem, mevcut piyasa verilerini inceleyerek evin güncel tahmini değerini hesaplar. Ayrıca geçmiş fiyat değişimleri ve mevcut piyasa eğilimleri dikkate alınarak gelecekteki olası değer tahmini de sunulur.

Bu sayede kullanıcılar yatırım veya satın alma kararlarını daha bilinçli şekilde verebilirler.

---

# Kullanılan Teknolojiler ve Kütüphaneler

## Programlama Dili

* Python

## Kullanılan Teknolojiler

* HTML
* CSS
* JavaScript
* Python
* Yapay Zeka / Makine Öğrenmesi Algoritmaları

## Kullanılan Kütüphaneler

* Pandas
* NumPy
* Scikit-Learn
* Flask
* Requests
* BeautifulSoup

(Not: Kullanılan kütüphaneler projeye göre düzenlenebilir.)

---

# Proje Klasör Yapısı

```text
AI_Ev_Fiyat_Tahmini/
│
├── app.py
├── model.py
├── scraper.py
├── requirements.txt
├── README.md
│
├── data/
│   └── housing_data.csv
│
├── models/
│   └── trained_model.pkl
│
├── templates/
│   ├── index.html
│   └── result.html
│
└── static/
    ├── css/
    └── images/
```

---

# Kurulum Adımları

1. GitHub reposunu bilgisayara klonlayın.

```bash
git clone [GitHub_Proje_Linki]
```

2. Proje klasörüne girin.

```bash
cd AI_Ev_Fiyat_Tahmini
```

3. Gerekli kütüphaneleri yükleyin.

```bash
pip install -r requirements.txt
```

---

# Çalıştırma Talimatları

Uygulamayı çalıştırmak için aşağıdaki komutu kullanınız:

```bash
python app.py
```

Ardından tarayıcı üzerinden ilgili yerel adres açılarak uygulama kullanılabilir.

---

# Kullanım Talimatları

1. Web sitesi açılır.
2. Kullanıcı analiz yapmak istediği bölgeyi seçer.
3. Sistem emlak ilanlarından elde edilen verileri işler.
4. Yapay zeka modeli mevcut piyasa değerini hesaplar.
5. Gelecekteki tahmini değer kullanıcıya gösterilir.
6. Sonuçlar grafik veya rapor şeklinde görüntülenebilir.

---

# GitHub Proje Bağlantısı

GitHub bağlantınızı buraya ekleyiniz:

https://github.com/Mehmetcelebi0/AI-Destekli-Ev-Fiyat-Tahmini-Uygulamas-

---

# Kaynakça

1. Python Resmi Dokümantasyonu
   https://docs.python.org/

2. Pandas Dokümantasyonu
   https://pandas.pydata.org/

3. NumPy Dokümantasyonu
   https://numpy.org/

4. Scikit-Learn Dokümantasyonu
   https://scikit-learn.org/

5. Flask Dokümantasyonu
   https://flask.palletsprojects.com/

6. Projede kullanılan emlak veri kaynakları ve ilan siteleri

---

# Sonuç

Bu proje, emlak piyasasında veri analizi ve yapay zeka teknolojilerini kullanarak konut fiyatlarının tahmin edilmesini amaçlamaktadır. Gerçek ilan verilerinden elde edilen bilgiler sayesinde kullanıcılar hem mevcut piyasa değerlerini hem de gelecekteki olası fiyat değişimlerini analiz edebilmektedir.

NOT: Github' da dosya yükleme sınırı olduğundan kaynaklı joblib dosyaları ayrı olarak drive linki şeklinde gönderilmiştir.

link: https://drive.google.com/drive/folders/1t2aR_OC_n8NK391DF0uC_zm9tziWReIG?usp=drive_link

adresinden joblib dosyalarına ulaşabilirsiniz.
