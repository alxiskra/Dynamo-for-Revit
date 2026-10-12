1. **[CreateRoomViews_R22.py](https://github.com/alxiskra/Dynamo-for-Revit/blob/main/CreateRoomViews_R22.py)**

   Пакетное создание 3D видов по выбранным помещениям (включая помещения связанных моделей) с автоматической подрезкой габаритов (по Section Box). **Скрипт включает удобный UI** с поиском, быстрым запуском (помещения из связей подгружаются только при их выборе в окне) и шкалой прогресса с возможностью безопасной отмены.
   <details>
     <summary><b>▶Play Demo</b></summary>
     <br>
     <video src="https://github.com/user-attachments/assets/a08e4b85-98ef-4971-8830-f86b282515f1" width="800" controls></video>
   </details>

   ---
   
1. **[CreateWorksetView_R22.py](https://github.com/alxiskra/Dynamo-for-Revit/blob/main/CreateWorksetView_R22.py)**
   
    Пакетное создание или обновление 3D видов рабочих наборов для визуальной проверки модели. При выборе режима обновления виды рабочих наборов не создаются заново, а обновляются имеющиеся, что экономит время: скрипт сбрасывает их до «чистого» состояния (отвязываются шаблоны, убираются фильтры, включаются скрытые категории, обновляется видимость рабочих наборов и отключается подрезка вида). **Скрипт включает удобный UI** с поиском, выбором режима работы («Создать новые» или «Обновить существующие») и шкалой прогресса с возможностью безопасной отмены.
   <details>
     <summary><b>▶Play Demo (v1)</b></summary>
     <br>
     <video src="https://github.com/user-attachments/assets/bffde413-cc6f-4cfb-b42d-6f2827ee1326" width="800" controls></video>
   </details>

   ---

1. **[GetActiveSelection_R22.py](https://github.com/alxiskra/Dynamo-for-Revit/blob/main/GetActiveSelection_R22.py)**
   
    Передать в Dynamo выделенные Revit-элементы, для дальнейшей работе с ними внутри него. Например можно быстро получить выделенные в диспетчере листы, а затем с помощью последующих нодов экспортировать листы в PDF.
   <details>
     <summary><b>▶Play Demo</b></summary>
     <br>
     <video src="https://github.com/user-attachments/assets/6827c8ba-50f3-4f9d-ae09-270375601ae3" width="800" controls></video>
   </details>
