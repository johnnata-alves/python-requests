from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    writer.add_page(page)

writer.encrypt("123456")

with open("output_protegido.pdf", "wb") as f:
    writer.write(f)
