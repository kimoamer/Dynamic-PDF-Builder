"""The sample report every theme is judged on, in English and Arabic."""
EN = """---
title: Annual Review 2026
subject: Growth across every region
author: Finance department
date: November 2026
---

# Annual Review 2026

## Highlights

Revenue grew in every region this year, led by the north, while costs held below plan. The second production line opened in March and reached full output by June, two months ahead of schedule.

:::metrics
Revenue | $48.2M | +12%
Margin | 31.4% | +2.1pt
Customers | 1,284 | +9%
:::

> Growth this year came from customers we already had, and that is the kind that lasts.
> — Chief Executive

## Results by region

Sales rose fastest where the new line shortened delivery times. The table sets out revenue and its share by region.

| Region | Revenue ($M) | Share | Change |
|---|---:|---:|---:|
| North | 18.4 | 38% | +16% |
| East | 12.1 | 25% | +11% |
| South | 9.6 | 20% | +8% |
| West | 8.1 | 17% | +10% |
| Total | 48.2 | 100% | +12% |

Table: Revenue by region

```chart
{"type": "bar", "title": "Revenue by region ($M)", "data": {"North": 18.4, "East": 12.1, "South": 9.6, "West": 8.1}}
```

:::tip
Orders booked for the first quarter of next year already cover 70% of its plan.
:::

## Outlook

We expect steady growth next year. The priorities are margin, cash and the people who deliver both.

1. Raise the margin by one point through purchasing.
2. Shorten the cash cycle by ten days.
3. Train forty supervisors.

### Risks

- Energy prices may rise faster than planned.
- Two large contracts renew in the second half.
"""
AR = """---
title: المراجعة السنوية 2026
subject: نمو في كل المناطق
author: الإدارة المالية
date: نوفمبر 2026
language: ar
---

# المراجعة السنوية 2026

## أبرز النتائج

نمت الإيرادات في كل المناطق هذا العام بقيادة الشمال، وبقيت التكاليف دون الخطة. افتُتح خط الإنتاج الثاني في مارس وبلغ طاقته الكاملة في يونيو قبل الموعد بشهرين.

:::metrics
الإيرادات | 48.2 مليون | +12%
الهامش | 31.4% | +2.1
العملاء | 1,284 | +9%
:::

> جاء نمو هذا العام من عملائنا الحاليين، وهذا هو النمو الذي يدوم.
> — الرئيس التنفيذي

## النتائج حسب المنطقة

ارتفعت المبيعات أسرع حيث قصّر الخط الجديد مدة التسليم. ويوضح الجدول الإيرادات وحصة كل منطقة.

| المنطقة | الإيرادات (مليون) | الحصة | التغير |
|---|---:|---:|---:|
| الشمال | 18.4 | 38% | +16% |
| الشرق | 12.1 | 25% | +11% |
| الجنوب | 9.6 | 20% | +8% |
| الغرب | 8.1 | 17% | +10% |
| الإجمالي | 48.2 | 100% | +12% |

Table: الإيرادات حسب المنطقة

:::tip
الطلبات المحجوزة للربع الأول من العام القادم تغطي 70% من خطته.
:::

## التوقعات

نتوقع نموًا مستقرًا في العام القادم. الأولويات هي الهامش والنقد والأشخاص الذين يحققونهما.

1. رفع الهامش نقطة واحدة عبر المشتريات.
2. تقصير دورة النقد عشرة أيام.
3. تدريب أربعين مشرفًا.
"""
