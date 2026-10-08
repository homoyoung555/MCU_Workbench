using System;
using System.Linq;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace PT102_Btl_hex_to_chromapat
{
    class PT102_BootProgram
    {
        //public static string StilPath = @"D:\\CP_Pattern\\Start\\";
        //public static string StilPath_new = @"D:\\CP_Pattern\\end\\";

        public static string StilPath = @"D:\\01_Work\\CP_Map_Change\\Hex\\";
        public static string StilPath_new = @"D:\\01_Work\\CP_Map_Change\\Pat\\";

        public static int cyc_count = 0;
        public static bool addr_first = true;
        public static int addr_end_num = 0;
        public static int Erase_delay = 25000;//T=0.2uS,Erase=5mS
        public static int Pgm_delay = 7500;//T=0.2uS,Pgm=1.5mS
        public static int PageSize = 512;
        public static int Addroffset = 0;

        public static int BtlEndAddr = 0x38;

        static void Main(string[] args)
        {

            DirectoryInfo root = new DirectoryInfo(StilPath);
            FileInfo[] thefileInfo = root.GetFiles("*.hex");

            foreach (FileInfo NextFile in thefileInfo)
            {
                cyc_count = 0;
                string strFileName = NextFile.Name.Substring(0, NextFile.Name.IndexOf(".hex"));//获取新生成的pat文件名
                Console.WriteLine(strFileName);
                if (Read(NextFile.FullName, strFileName))
                    Console.WriteLine("解析成功");
                else
                    Console.WriteLine("解析失败");

                addr_first = true;
                addr_end_num = 0;
            }
            Console.ReadLine();
        }

        static public bool Read(string pathSrc, string pathDet)
        {
            bool bSuccess = true;
            StreamReader sr = new StreamReader(pathSrc, Encoding.Default);
            StreamWriter sw = new StreamWriter(StilPath_new + pathDet + ".pat");

            //SCLK,SDA,NRST
            string InitialStr = " *11*;";//初始字符串
            string line = "";


            Pat_header(sw, pathDet);
            
            Enter_Fbist_mode(sw);
            //Read_trim_mode(sw);//Read the data in flash special row to corresponding trim registers.PT102 not support
            for (int index = 0; index < BtlEndAddr; index++)
            {
                PagePre_program_test(sw, InitialStr, index);
                Page_erase_test(sw, InitialStr);
            }

            //write
            while ((line = sr.ReadLine()) != null)
            {
                Write_pat(sw, line, InitialStr);
            }
            sr.Close();
            
            //read

            sr = new StreamReader(pathSrc, Encoding.Default);
            while ((line = sr.ReadLine()) != null)
            {
                Read_pat(sw, line, InitialStr);
            }


            Pat_end(sw);
            sr.Close();
            sw.Close();
            return bSuccess;
        }

        static void Pat_header(StreamWriter sw, string TxtName)
        {
            string PatName = "SPM_PATTERN() {";
            PatName = PatName.Insert(PatName.IndexOf("(") + 1, TxtName);

            sw.WriteLine("SET_DEC_FILE  \"pin.dec\"");
            sw.WriteLine("");
            sw.WriteLine("HEADER");
            sw.WriteLine("PA14,PA13,PF5;");//SCLK,SDA,NRST
            sw.WriteLine(PatName);
            sw.WriteLine("");

            sw.WriteLine(" *011*TS1;");
            sw.WriteLine(" *011*;");
            sw.WriteLine(" *011*RPT 100;");
            sw.WriteLine(" *011*;");
            sw.WriteLine(" *111*;");
        }

        static void Pat_end(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *011*STOP;");
            sw.WriteLine("}");
        }

        static void Enter_Fbist_mode(StreamWriter sw)
        {
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *110*;//0xB5");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;//0x94");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *110*;//0xD9");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");

        }


        static void Read_trim_mode(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 58;");
            sw.WriteLine(" *101*;");
        }

        static void Write_pagelatch(StreamWriter sw)
        {
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
        }

        static void Tcy_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 10;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *0X0*;");
        }
        static void Ts1_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 80;");//>15us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts2p_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 30;");//>5us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Preprog_Delay_pt100(StreamWriter sw)
        {

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*RPT 1000;");//200us，T=200ns
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
        }

        static void Erase_Delay_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS5;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*RPT " + Erase_delay.ToString() + ";");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *111*;");
        }

        static void Prog_Delay_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");//sw.WriteLine(" *111*TS6;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT " + Pgm_delay.ToString() + ";");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *101*;");
        }

        static void Tps3_pt100(StreamWriter sw)
        {
            //sw.WriteLine(" *110*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 350;");//>60us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts3_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 30;");//>5us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts0_pt100(StreamWriter sw)
        {
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 60;");//>6us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void PagePre_program_test(StreamWriter sw, String InitialStr, int pageAddr)
        {
            //set 010 0101, 7'h0,bank_en[1:0]=01
            Write_fbist_reg(sw, 0x25, 0x0080, InitialStr);

            //set 010 0011, opr_sel[1:0]=00,bank_sel[1:0]=01
            Write_fbist_reg(sw, 0x23, 0x0001, InitialStr);

            //set 001 1101, 7'h0,RA[8:0]
            Write_fbist_reg(sw, 0x1D, pageAddr, InitialStr);//addr,data

            //set 001 1110,5'h0,AXA,CA[3:0],PA[5:0]
            Write_fbist_reg(sw, 0x1E, 0x0400, InitialStr);//addr,data
            Tcy_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0111
            Write_fbist_reg(sw, 0x1F, 0x0007, InitialStr);
            Tcy_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=01, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x001C, InitialStr);
            Ts1_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x002C, InitialStr);
            Ts2p_pt100(sw);

            //set 001 1111, 9’b0,PE=1,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x006C, InitialStr);
            Preprog_Delay_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x002C, InitialStr);
            Tps3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=11, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x003C, InitialStr);
            Ts3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x000C, InitialStr);
            Ts3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);
            Ts0_pt100(sw);
        }
        static void Page_erase_test(StreamWriter sw, String InitialStr)
        {
            //set 010 0011, opr_sel[1:0]=01,bank_sel[1:0]=01
            Write_fbist_reg(sw, 0x23, 0x0005, InitialStr);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=01, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x0018, InitialStr);
            Ts1_pt100(sw);
            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x0028, InitialStr);
            Ts2p_pt100(sw);

            //set 001 1111, 9’b0,PE=1,SEQ[1:0]=10, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x0068, InitialStr);
            Erase_Delay_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x0028, InitialStr);
            Tps3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=11, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x0038, InitialStr);
            Ts3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=1000
            Write_fbist_reg(sw, 0x1F, 0x008, InitialStr);
            Ts0_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);
            Tcy_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0001
            Write_fbist_reg(sw, 0x1F, 0x0001, InitialStr);
            Tcy_pt100(sw);
        }

        static void Prog_addr_test(StreamWriter sw, String InitialStr, int addrLength)
        {
            //set 010 0101, 7'h0,bank_en[1:0]=01
            Write_fbist_reg(sw, 0x25, 0x0080, InitialStr);

            //set 010 0011, 12'h0,opr_sel[1:0]=10,bank_sel[1:0]=01
            Write_fbist_reg(sw, 0x23, 0x0009, InitialStr);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);

            //set 001 1110, 5'h0,AXA=0,CA[4:0],PA[4:0]
            Write_fbist_reg(sw, 0x1E, 0x0400, InitialStr);

            //sw.WriteLine(" //addr");
            //set RA
            Write_fbist_reg(sw, 0x1D, addrLength / PageSize, InitialStr);//addr,data

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0001
            Write_fbist_reg(sw, 0x1F, 0x0001, InitialStr);
            Tcy_pt100(sw);//???

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0110
            Write_fbist_reg(sw, 0x1F, 0x0006, InitialStr);
            Tcy_pt100(sw);

        }

        static void Prog_PEdelay_test(StreamWriter sw, String InitialStr)
        {
            //set 010 0011, opr_sel[1:0]=10,bank_sel[1:0]=01
            Write_fbist_reg(sw, 0x23, 0x0009, InitialStr);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=01, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x001C, InitialStr);
            Ts1_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x002C, InitialStr);
            Ts2p_pt100(sw);

            //set 001 1111, 9’b0,PE=1,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x006C, InitialStr);
            Prog_Delay_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=10, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x002C, InitialStr);
            Tps3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=11, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x003C, InitialStr);
            Ts3_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=1100
            Write_fbist_reg(sw, 0x1F, 0x000C, InitialStr);
            Ts0_pt100(sw);

            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);
            Tcy_pt100(sw);

        }
        static void Read_addr_test(StreamWriter sw, String InitialStr, int addrLength)
        {
            //set 001 1111, 9’b0,PE=0,SEQ[1:0]=00, MODE[3:0]=0101
            Write_fbist_reg(sw, 0x1F, 0x0005, InitialStr);

            //set 001 1110, 5'h0,AXA=0,CA[4:0],PA[4:0]
            Write_fbist_reg(sw, 0x1E, 0x0400, InitialStr);

            //set RA
            Write_fbist_reg(sw, 0x1D, addrLength / PageSize, InitialStr);//addr,data

            //set read_mode=1 continue read
            Write_fbist_reg(sw, 0x20, 0x0800, InitialStr);
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *1L1*;"); //dummy
        }


        static void Write_fbist_reg(StreamWriter sw, int addr, int data, String StartStr)
        {
            string AddrStr = Convert.ToString(addr, 2).PadLeft(7, '0');//将int类型的值转换为7bit长度的字符串
            //AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string DataStr = Convert.ToString(data, 2).PadLeft(16, '0');
            //DataStr = new string(DataStr.ToCharArray().Reverse().ToArray());
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            for (int i = 0; i < AddrStr.Length; i++)
            {
                sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)));
            }
            for (int i = 0; i < DataStr.Length; i++)
            {
                sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));

                if (i == DataStr.Length - 1) sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));
            }

        }


        // 计算128位数据的9位ECC（汉明码）校验码
        static int[] GetECC(int[] dataIn)
        {

            int[] ECCbit = new int[9] { 0, 0, 0, 0, 0, 0, 0, 0, 0 };

            int[] ECCB_8 = { 1,1,0,0,1,0,1,1,0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0,1,0,0,1,0,1,1,0,
                             0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1,0,1,1,0,1,0,0,1,
                             1,0,0,1,0,1,1,1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1,0,1,1,0,1,0,0,1,1,
                             0,0,1,0,1,1,0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,1,0,0,1,0,1,1,0,1,1,1 };
            int[] ECCB_7 = { 1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0 };
            int[] ECCB_6 = { 0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                             1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                             1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0 };
            int[] ECCB_5 = { 0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                             1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                             1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0 };
            int[] ECCB_4 = { 0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,
                             0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0 };
            int[] ECCB_3 = { 1,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,
                             0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,
                             0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,
                             0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,1,1,1,1,1,1,1,0,0,0,0 };
            int[] ECCB_2 = { 0,1,1,1,1,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,
                             1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,
                             1,1,1,1,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0,1,
                             1,1,1,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,0,0,0,1,1,1,1,0,0,0,1,1,1,0 };
            int[] ECCB_1 = { 0,1,1,0,0,1,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,
                             1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,
                             1,1,0,0,1,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,
                             1,0,0,1,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,1,1,0,0,1,1,0,1,1,0,1 };
            int[] ECCB_0 = { 0,1,0,1,0,1,0,1,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,
                             1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,
                             1,0,1,0,1,0,1,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,
                             0,1,0,1,0,1,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,1,0,1,0,1,0,1,1,0,1,1 };

            //////////////bit8//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[8] = ((1 ^ dataIn[index]) & ECCB_8[index]);
                }
                else
                {
                    ECCbit[8] ^= (dataIn[index] & ECCB_8[index]);
                }
            }

            //////////////bit7//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[7] = ((1 ^ dataIn[index]) & ECCB_7[index]);
                }
                else
                {

                    ECCbit[7] ^= (dataIn[index] & ECCB_7[index]);
                }
            }

            //////////////bit6//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[6] = ((1 ^ dataIn[index]) & ECCB_6[index]);
                }
                else
                {

                    ECCbit[6] ^= (dataIn[index] & ECCB_6[index]);

                }
            }
            //////////////bit5//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[5] = ((1 ^ dataIn[index]) & ECCB_5[index]);
                }
                else
                {

                    ECCbit[5] ^= (dataIn[index] & ECCB_5[index]);

                }
            }

            //////////////bit4//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[4] = ((1 ^ dataIn[index]) & ECCB_4[index]);
                }
                else
                {

                    ECCbit[4] ^= (dataIn[index] & ECCB_4[index]);

                }
            }

            //////////////bit3//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[3] = ((1 ^ dataIn[index]) & ECCB_3[index]);
                }
                else
                {

                    ECCbit[3] ^= (dataIn[index] & ECCB_3[index]);

                }
            }

            //////////////bit2//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[2] = ((1 ^ dataIn[index]) & ECCB_2[index]);
                }
                else
                {

                    ECCbit[2] ^= (dataIn[index] & ECCB_2[index]);

                }
            }

            //////////////bit1//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[1] = ((1 ^ dataIn[index]) & ECCB_1[index]);
                }
                else
                {

                    ECCbit[1] ^= (dataIn[index] & ECCB_1[index]);

                }
            }

            //////////////bit0//////////////////////
            for (int index = 0; index < 128; index++)
            {
                if (index == 0)
                {
                    ECCbit[0] = ((1 ^ dataIn[index]) & ECCB_0[index]);
                }
                else
                {

                    ECCbit[0] ^= (dataIn[index] & ECCB_0[index]);

                }
            }

            return ECCbit;

        }

        static int[] StringToBinary(string dataInStr)
        {
            int[] dataIn = new int[128];
            string DataBinaryStr = null;
            for (int j = 0; j < 16; j++)
            {
                int index = (j / 16) * 16 + 15 - (j % 16);//每次写16，高位先发
                int writedata = DataStr_to_int(dataInStr.Substring(index * 2, 2));
                DataBinaryStr += Convert.ToString(writedata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
            }
            for (int index = 0; index < DataBinaryStr.Length; index++)
            {
                dataIn[index] = int.Parse(DataBinaryStr.Substring(index, 1));
            }

            return dataIn;
        }

        static void Write_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;
            if (DataStr.Substring(7, 2) == "00") effective_data = true;//hex 文件“00”表示数据有效

            if (effective_data)
            {
                int addrLength = AddrStr_to_int(DataStr.Substring(3, 4));//获取地址2Byte

                if (addrLength % 512 == 0) Prog_addr_test(sw, InitialStr, addrLength);//每page写一次地址

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要写入数据的长度
                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }

                Write_pagelatch(sw);//每次写16Byte前，先发write pagelatch命令

                string dataInStr = DataStr.Substring(9, 32);
                int[] dataIn = StringToBinary(dataInStr);
                int[] ECCbit = GetECC(dataIn);

                for (int index = 0; index < ECCbit.Length; index++)
                {
                    if (index == 0)
                        sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString()) + "//ECCbit");
                    else
                        sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString()));
                }

                for (int j = 0; j < dataLength; j++)
                {

                    int index = (j / 16) * 16 + 15 - (j % 16);//每次写16，高位先发
                    int writedata = DataStr_to_int(DataStr.Substring(9 + index * 2, 2));
                    //每16Bytes最高位取反
                    if (j == 0) writedata ^= 0x80;

                    string DataBinaryStr = Convert.ToString(writedata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串

                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", writedata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));

                        if ((j + 1) % 16 == 0 && i == DataBinaryStr.Length) sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));//每写4word,最后1bit补一个周期
                    }

                    addr_end_num = addrLength + j + 1;
                }

                if (addr_end_num % 512 == 0) Prog_PEdelay_test(sw, InitialStr);//每page delay一次

            }

            //if (DataStr.Substring(7, 2) == "05" && (addr_end_num % 512 != 0))
            //    Prog_PEdelay_test(sw, InitialStr);//end
            if (DataStr.Substring(7, 2) == "05" && (addr_end_num % PageSize != 0))
            {
                int dataLength = PageSize - (addr_end_num % PageSize);
                for (int j = 0; j < dataLength; j++)
                {
                    if (j % 16 == 0)
                    {
                        Write_pagelatch(sw);//每次写16Byte前，先发write pagelatch命令
                        string dataInStr = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF";
                        int[] dataIn = StringToBinary(dataInStr);
                        int[] ECCbit = GetECC(dataIn);

                        for (int index = 0; index < ECCbit.Length; index++)
                        {
                            if (index == 0)
                                sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString()) + "//ECCbit");
                            else
                                sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString()));
                        }
                    }

                    int writedata = 0xFF;
                    if (j % 16 == 0) writedata ^= 0x80;

                    string DataBinaryStr = Convert.ToString(writedata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串

                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", writedata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));

                        if ((j + 1) % 16 == 0 && i == DataBinaryStr.Length) sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));//每写4byte,最后1bit补一个周期
                    }

                }

                Prog_PEdelay_test(sw, InitialStr);//end
            }

        }
        static void Read_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;

            if (DataStr.Substring(7, 2) == "00") effective_data = true;//hex 文件“00”表示数据有效


            if (effective_data)
            {
                if (addr_first)
                {
                    int addrLength = AddrStr_to_int(DataStr.Substring(3, 4));//获取地址2Byte
                    if (addrLength % 512 == 0) Read_addr_test(sw, InitialStr, addrLength);

                }

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要读取数据的长度

                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }

                string dataInStr = DataStr.Substring(9, 32);
                int[] dataIn = StringToBinary(dataInStr);
                int[] ECCbit = GetECC(dataIn);

                if (addr_first == false) //每次读4word(16Byte)前，先发read命令
                {
                    sw.WriteLine(" *111*;");
                    sw.WriteLine(" *1L1*;");
                }
                for (int index = 0; index < ECCbit.Length; index++)
                {
                    if (index == 0)
                        sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString().Replace('1', 'H').Replace('0', 'L')) + "//ECCbit");
                    else
                        sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, ECCbit[8 - index].ToString().Replace('1', 'H').Replace('0', 'L')));
                }

                for (int j = 0; j < 16; j++)//j < dataLength
                {

                    int index = (j / 16) * 16 + 15 - (j % 16);//每次读4word(16Byte)，高位先发
                    int readdata = DataStr_to_int(DataStr.Substring(9 + index * 2, 2));
                    //每16Bytes最高位取反
                    if (j == 0) readdata ^= 0x80;

                    string DataBinaryStr = Convert.ToString(readdata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串
                    DataBinaryStr = DataBinaryStr.Replace('1', 'H');
                    DataBinaryStr = DataBinaryStr.Replace('0', 'L');
                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", readdata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));
                    }
                    addr_first = false;
                }



            }
        }



        static public int AddrStr_to_int(string DataStr)
        {
            int bit0 = Convert.ToChar(DataStr.Substring(0, 1));
            int bit1 = Convert.ToChar(DataStr.Substring(1, 1));
            int bit2 = Convert.ToChar(DataStr.Substring(2, 1));
            int bit3 = Convert.ToChar(DataStr.Substring(3, 1));

            int length = 0;

            if (bit0 >= 65) length += (bit0 - 55) * 16 * 16 * 16;
            else length += (bit0 - 48) * 16 * 16 * 16;

            if (bit1 >= 65) length += (bit1 - 55) * 16 * 16;
            else length += (bit1 - 48) * 16 * 16;

            if (bit2 >= 65) length += (bit2 - 55) * 16;
            else length += (bit2 - 48) * 16;

            if (bit3 >= 65) length += (bit3 - 55) * 1;
            else length += (bit3 - 48) * 1;

            return length;
        }

        static public int DataStr_to_int(string DataStr)
        {
            int high_po = Convert.ToChar(DataStr.Substring(0, 1));
            int low_pol = Convert.ToChar(DataStr.Substring(1, 1));
            int length = 0;

            if (high_po >= 65) length += (high_po - 55) * 16;
            else length += (high_po - 48) * 16;

            if (low_pol >= 65) length += (low_pol - 55);
            else length += (low_pol - 48);

            return length;
        }


        static public string GetValue(string line, int[] index_save, int length)
        {
            string value = "";
            string timeset = "";
            StringBuilder value1 = new StringBuilder();

            line = line.Substring(0, line.LastIndexOf(";") + 1);
            line = Regex.Replace(line, @"\s", "");
            timeset = line.Substring(line.LastIndexOf("*"), (line.LastIndexOf(";") + 1 - line.LastIndexOf("*")));


            for (int cyc = 0; cyc < length; cyc++)
            {
                //value += line[index_save[cyc]];
                value1.Append(line[index_save[cyc]]);
            }
            value = value1.ToString();

            value = " *" + value + timeset + "//r" + (cyc_count++).ToString();
            return value;
        }


    }
}
